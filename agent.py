"""
Paper-to-Repo Agent — Enhanced Edition
Features: Semantic Scholar API, self-refinement loop, execution sandbox,
          SQLite fingerprinting, GitHub auto-push, SSE progress callbacks.
"""

import os, io, ast, json, uuid, hashlib, zipfile, sqlite3, base64
import shutil, subprocess, tempfile, requests, argparse, fitz, random, re
from typing import List, Dict, Optional, Callable
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from ddgs import DDGS

load_dotenv(override=True)

_key = os.environ.get("GEMINI_API_KEY", "")
print(f"[startup] GEMINI_API_KEY: {'YES — ' + _key[:8] + '...' if _key else 'MISSING'}")

DB_PATH = os.path.join(os.path.dirname(__file__), "papers.db")


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            paper_hash   TEXT PRIMARY KEY,
            title        TEXT,
            zip_bytes    BLOB,
            quality      INTEGER,
            created_at   TEXT
        )
    """)
    conn.commit()
    conn.close()


_init_db()


class PaperToRepoAgent:

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY missing. Get one free at https://aistudio.google.com/")
        
        self.client = genai.Client(api_key=self.api_key)
        self.model = "gemini-1.5-flash"

    # ------------------------------------------------------------------ helpers
    def _generate(self, prompt: str, max_tokens: int = 3000) -> str:
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.3,
                )
            )
            return resp.text
        except Exception as e:
            raise Exception(f"Gemini API Error: {str(e)}")

    def _parse_files(self, response: str) -> Dict[str, str]:
        files = {}
        for section in response.split("FILENAME:")[1:]:
            lines = section.strip().split("\n")
            fname = lines[0].strip()
            s, e = -1, -1
            for i, ln in enumerate(lines):
                if ln.strip().startswith("```"):
                    if s == -1:
                        s = i + 1
                    else:
                        e = i
                        break
            if s != -1 and e != -1:
                files[fname] = "\n".join(lines[s:e])
        return files

    # ------------------------------------------------------------- cache (SQLite)
    def _paper_hash(self, paper: Dict) -> str:
        key = (paper.get("title", "") + paper.get("link", "")).encode()
        return hashlib.sha256(key).hexdigest()

    def _cache_get(self, h: str) -> Optional[bytes]:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT zip_bytes FROM papers WHERE paper_hash=?", (h,)).fetchone()
        conn.close()
        return bytes(row[0]) if row else None

    def _cache_set(self, h: str, paper: Dict, zip_bytes: bytes, quality: int):
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO papers VALUES (?,?,?,?,?)",
            (h, paper.get("title"), zip_bytes, quality, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    # -------------------------------------------------- 1. CoT topic extraction
    def extract_research_areas(self, job_description: str) -> List[str]:
        print("\n🔍 Chain-of-thought topic extraction...")
        prompt = f"""You are a senior research scientist reviewing a job description.
Identify research topics that yield the most relevant recent papers (2023-2025).

Job Description:
{job_description}

Think step by step:
STEP 1 — Role Analysis: What is the core research mission? What hard problems are they solving?
STEP 2 — Tech Stack: What specific ML architectures/algorithms are central?
STEP 3 — Research Frontier: What bleeding-edge open problems does this role touch?
STEP 4 — Search Strategy: Choose 5 precise, searchable subfields (e.g. "vision-language pre-training", not "computer vision").

After reasoning, output ONLY a JSON array of 5 terms:
["term1", "term2", "term3", "term4", "term5"]
"""
        text = self._generate(prompt, max_tokens=800)
        s, e = text.rfind("["), text.rfind("]") + 1
        if s != -1 and e > s:
            try:
                kw = json.loads(text[s:e])
                print(f"   Topics: {', '.join(kw)}")
                return kw
            except json.JSONDecodeError:
                pass
        print("   Warning: fallback topic extraction")
        return [text[:80]]

    # ----------------------------------------------- 2. Semantic Scholar search
    def _semantic_scholar(self, query: str, limit: int = 6) -> List[Dict]:
        try:
            r = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query, "limit": limit,
                    "fields": "title,authors,abstract,year,citationCount,openAccessPdf,externalIds,venue",
                },
                timeout=10,
            )
            if r.status_code == 200:
                out = []
                for p in r.json().get("data", []):
                    arxiv = p.get("externalIds", {}).get("ArXiv", "")
                    link = f"https://arxiv.org/abs/{arxiv}" if arxiv else \
                           (p.get("openAccessPdf") or {}).get("url", "")
                    authors = ", ".join(a["name"] for a in p.get("authors", [])[:3])
                    if len(p.get("authors", [])) > 3:
                        authors += " et al."
                    out.append({
                        "title": p.get("title", ""),
                        "authors": authors,
                        "year": p.get("year", ""),
                        "abstract": p.get("abstract", ""),
                        "citations": p.get("citationCount", 0),
                        "venue": p.get("venue", ""),
                        "link": link,
                    })
                return out
        except Exception as ex:
            print(f"   Semantic Scholar warning: {ex}")
        return []

    def find_papers(self, research_areas: List[str], job_description: str) -> List[Dict]:
        print("\n📚 Searching Semantic Scholar...")
        raw: List[Dict] = []
        for area in research_areas[:5]:
            results = self._semantic_scholar(area, limit=5)
            print(f"   '{area}' → {len(results)} papers")
            raw.extend(results)

        if not raw:
            print("   Falling back to DuckDuckGo...")
            with DDGS() as ddgs:
                for area in research_areas[:5]:
                    try:
                        raw.extend(list(ddgs.text(f"{area} research paper arxiv 2024 2025", max_results=5)))
                    except Exception:
                        pass

        if not raw:
            return []

        seen: set = set()
        unique: List[Dict] = []
        for r in raw:
            key = (r.get("title", "") or "").lower()[:50]
            if key and key not in seen:
                seen.add(key)
                unique.append(r)

        context = json.dumps([{
            "title": r.get("title"),
            "authors": r.get("authors"),
            "year": r.get("year"),
            "abstract": (r.get("abstract") or r.get("snippet", ""))[:300],
            "citations": r.get("citations", 0),
            "venue": r.get("venue", ""),
            "link": r.get("link") or r.get("href", ""),
        } for r in unique[:20]], indent=2)

        print(f"   Ranking {min(len(unique), 20)} candidates...")

        prompt = f"""You are a senior research scientist selecting papers for this role:

Job: {job_description[:400]}
Areas needed: {', '.join(research_areas)}

Papers from Semantic Scholar:
{context}

Select TOP 5 most relevant papers. Score each 0-100 (relevancy_score).
Prefer: 2023-2025 papers, highly cited, top venues (NeurIPS/ICML/ICLR/CVPR).

Return ONLY a JSON array:
[{{"title":"...","authors":"...","link":"...","summary":"one sentence","relevance":"why relevant","key_result":"result to reproduce","relevancy_score":92}}]
"""
        text = self._generate(prompt, max_tokens=2000)
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            s, e = text.find("["), text.rfind("]") + 1
            if s != -1 and e > s:
                papers = json.loads(text[s:e])
                print(f"\n   Selected {len(papers)} papers:")
                for i, p in enumerate(papers, 1):
                    print(f"   {i}. [{p.get('relevancy_score','?')}%] {p['title']}")
                for p in papers:
                    p["cached"] = self._cache_get(self._paper_hash(p)) is not None
                return papers
        except json.JSONDecodeError as ex:
            print(f"   JSON error: {ex}")
        return []

    # ---------------------------------------------- 3. Code generation + refine
    def _download_and_extract_pdf(self, paper: Dict) -> str:
        """Download the PDF (e.g., from arXiv) and extract all text for full-context RAG."""
        link = paper.get("link", "")
        if not link:
            return ""

        # Convert arXiv abs link to pdf link
        if "arxiv.org/abs/" in link:
            link = link.replace("/abs/", "/pdf/")
            if not link.endswith(".pdf"):
                link += ".pdf"

        print(f"   📥 Downloading PDF from: {link}")
        try:
            r = requests.get(link, timeout=15)
            if r.status_code == 200:
                doc = fitz.open(stream=r.content, filetype="pdf")
                text = ""
                # Extract text from pages (limit to 15 to avoid massive books)
                for page in doc[:15]:
                    text += page.get_text() + "\n"
                
                # Smart Token Saver: Strip out references, bibliography, and appendices
                ref_match = re.search(r'\n(References|REFERENCES|Bibliography|BIBLIOGRAPHY)\s*\n', text)
                if ref_match:
                    text = text[:ref_match.start()]
                
                ack_match = re.search(r'\n(Acknowledgments|ACKNOWLEDGMENTS|Acknowledgements|ACKNOWLEDGEMENTS)\s*\n', text)
                if ack_match:
                    text = text[:ack_match.start()]
                
                print(f"   ✅ Extracted {len(text)} characters from PDF (filtered core)")
                
                # Truncate to 25,000 chars (~6,000 tokens). This is almost purely Intro + Methodology
                return text[:25000]
            else:
                print(f"   ⚠️ PDF download failed with status {r.status_code}")
        except Exception as ex:
            print(f"   ⚠️ PDF extraction error: {ex}")
        return ""

    def _impl_prompt(self, paper: Dict, pdf_text: str = "") -> str:
        pdf_context = f"\n\n--- FULL PAPER TEXT ---\n{pdf_text}\n--- END FULL PAPER TEXT ---\n" if pdf_text else ""
        return f"""You are an expert AI researcher and engineer. Your task is to implement the following paper in Python.

Title: {paper['title']}
Key result to reproduce: {paper['key_result']}
{pdf_context}

CRITICAL INSTRUCTIONS:
1. You MUST write the code to reproduce the key result based on the provided paper text.
2. You MUST output EXACTLY 3 files.
3. You MUST use EXACTLY the format below. 
4. DO NOT write any conversational text before or after. Start immediately with FILENAME: main.py.

FILENAME: main.py
```python
# Code goes here
```

FILENAME: requirements.txt
```
# Packages go here
```

FILENAME: README.md
```markdown
# Documentation goes here
```
"""

    def _refine_code(self, files: Dict[str, str], paper: Dict,
                     cb: Optional[Callable] = None) -> Dict[str, str]:
        if "main.py" not in files:
            return files
        if cb: cb("🔄 Self-refinement pass...")
        print("   🔄 Refining code...")
        prompt = f"""Review this Python implementation of "{paper['title']}".
Key result to reproduce: {paper['key_result']}

main.py:
{files['main.py']}

1. List up to 3 bugs or missing pieces.
2. Provide the complete fixed main.py.

ISSUES:
- ...

FILENAME: main.py
```python
<fixed code>
```
"""
        resp = self._generate(prompt, max_tokens=4000)
        fixed = self._parse_files(resp)
        if "main.py" in fixed and len(fixed["main.py"]) > 100:
            files["main.py"] = fixed["main.py"]
            print("   ✅ Refinement applied")
        return files

    # --------------------------------------------------- 4. Execution sandbox
    def _run_sandbox(self, files: Dict[str, str]) -> Dict:
        print("   🏃 Running execution sandbox (30s timeout)...")
        tmpdir = tempfile.mkdtemp(prefix="paper_repo_")
        try:
            for fname, content in files.items():
                fpath = os.path.join(tmpdir, fname)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w") as f:
                    f.write(content)
            result = subprocess.run(
                ["python", "main.py"],
                capture_output=True, text=True, timeout=30, cwd=tmpdir,
            )
            return {
                "ran": True, "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout[:800].strip(),
                "stderr": result.stderr[:400].strip(),
            }
        except subprocess.TimeoutExpired:
            return {"ran": True, "success": False, "stdout": "", "stderr": "Timed out after 30s", "returncode": -1}
        except Exception as ex:
            return {"ran": False, "success": False, "error": str(ex), "returncode": -1}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ----------------------------------------------- 5. Quality benchmark
    def evaluate_quality(self, files: Dict[str, str], paper: Dict,
                         sandbox: Optional[Dict] = None) -> Dict:
        print("   🔬 Running quality benchmark...")
        expected = {"main.py", "requirements.txt", "README.md"}
        present = set(files.keys())
        missing = expected - present
        structure = int(len(expected & present) / len(expected) * 25)

        syntax_errors = []
        for fn, content in files.items():
            if fn.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as ex:
                    syntax_errors.append(f"{fn}: {ex}")
        syntax = 25 if not syntax_errors else max(0, 25 - len(syntax_errors) * 8)

        code_sample = files.get("main.py", "")[:2000]
        readme_sample = files.get("README.md", "")[:500]
        eval_prompt = f"""Rate this implementation of "{paper['title']}" (key result: {paper['key_result']}).

main.py:
{code_sample}

README:
{readme_sample}

Rate correctness (0-25) and reproducibility (0-25).
Return ONLY JSON: {{"correctness":20,"reproducibility":18,"feedback":"one sentence"}}
"""
        llm = {"correctness": 15, "reproducibility": 15, "feedback": "LLM eval unavailable"}
        try:
            r = self._generate(eval_prompt, max_tokens=200)
            clean = r.replace("```json", "").replace("```", "").strip()
            s, e = clean.find("{"), clean.rfind("}") + 1
            if s != -1 and e > s:
                llm = json.loads(clean[s:e])
        except Exception:
            pass

        total = structure + syntax + llm.get("correctness", 15) + llm.get("reproducibility", 15)
        grade = "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 55 else "D"

        # Sandbox section
        sandbox_md = ""
        if sandbox:
            if sandbox.get("ran"):
                icon = "✅" if sandbox.get("success") else "❌"
                sandbox_md = f"\n## Execution Result\n{icon} Exit code: {sandbox.get('returncode')}\n"
                if sandbox.get("stdout"):
                    sandbox_md += f"\n**stdout:**\n```\n{sandbox['stdout']}\n```\n"
                if sandbox.get("stderr"):
                    sandbox_md += f"\n**stderr:**\n```\n{sandbox['stderr']}\n```\n"
            else:
                sandbox_md = f"\n## Execution Result\n⚠️ Could not run: {sandbox.get('error','unknown')}\n"

        syntax_line = "✅ All Python files parse without errors." if not syntax_errors \
            else "\n".join(f"❌ {e}" for e in syntax_errors)

        report_md = f"""# Quality Report

**Paper:** {paper['title']}
**Score:** {total}/100  (Grade: {grade})

## Breakdown

| Dimension | Score | Max |
|---|---|---|
| File Structure | {structure} | 25 |
| Syntax Validity | {syntax} | 25 |
| Algorithm Correctness | {llm.get('correctness','?')} | 25 |
| Reproducibility | {llm.get('reproducibility','?')} | 25 |
| **Total** | **{total}** | **100** |

## LLM Feedback
{llm.get('feedback','N/A')}

## File Structure
- Present: {', '.join(sorted(present)) or 'none'}
- Missing: {', '.join(sorted(missing)) or 'none'}

## Syntax Check
{syntax_line}
{sandbox_md}
---
*Generated by Paper-to-Repo Agent*
"""
        print(f"   Quality: {total}/100 (Grade {grade})")
        return {"total": total, "grade": grade, "report_md": report_md}

    # ----------------------------------------------- 6. GitHub auto-push
    def push_to_github(self, files: Dict[str, str], paper: Dict,
                       token: str, username: str) -> str:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in paper["title"][:50]).strip("-")
        repo_name = f"paper-impl-{safe}"

        create = requests.post(
            "https://api.github.com/user/repos",
            json={"name": repo_name, "description": f"Implementation of {paper['title']}", "private": False},
            headers=headers, timeout=10,
        )
        if create.status_code not in (200, 201):
            raise Exception(f"GitHub repo creation failed: {create.json().get('message')}")

        repo_url = create.json()["html_url"]
        for fname, content in files.items():
            encoded = base64.b64encode(content.encode()).decode()
            requests.put(
                f"https://api.github.com/repos/{username}/{repo_name}/contents/{fname}",
                json={"message": f"Add {fname}", "content": encoded},
                headers=headers, timeout=10,
            )
        print(f"   ✅ Pushed to GitHub: {repo_url}")
        return repo_url

    # ----------------------------------------------- main zip generation
    def generate_zip_bytes(self, paper: Dict,
                           cb: Optional[Callable] = None) -> bytes:
        # Check cache first
        h = self._paper_hash(paper)
        cached = self._cache_get(h)
        if cached:
            if cb: cb("⚡ Returning cached result...")
            print("   ⚡ Cache hit — returning cached zip")
            return cached

        if cb: cb("⚙️ Generating implementation...")
        print(f"\n⚙️  Generating: {paper['title']}")

        # Option 1 RAG: Download and extract full PDF text to inject into context
        if cb: cb("📥 Reading full PDF paper for context...")
        pdf_text = self._download_and_extract_pdf(paper)
        if pdf_text and cb: cb("🧠 Paper read! Writing code using full methodology...")

        # Requesting max_tokens=3000 ensures input_tokens + max_tokens stays under the 12,000 TPM limit
        response_text = self._generate(self._impl_prompt(paper, pdf_text), max_tokens=3000)
        files = self._parse_files(response_text)

        files = self._refine_code(files, paper, cb)

        if cb: cb("🏃 Running sandbox test...")
        sandbox = self._run_sandbox(files)

        if cb: cb("🔬 Benchmarking quality...")
        quality = self.evaluate_quality(files, paper, sandbox)
        files["quality_report.md"] = quality["report_md"]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in files.items():
                zf.writestr(fname, content)
        zip_bytes = buf.getvalue()

        self._cache_set(h, paper, zip_bytes, quality["total"])
        return zip_bytes

    # ----------------------------------------------- CLI mode
    def run(self, job_description: str, output_base_dir: str = "./generated_repos"):
        print("\n" + "=" * 60)
        print("🤖 PAPER-TO-REPO AGENT")
        print("=" * 60)

        areas = self.extract_research_areas(job_description)
        papers = self.find_papers(areas, job_description)
        if not papers:
            print("\n❌ No papers found.")
            return

        print("\n" + "-" * 60)
        for i, p in enumerate(papers, 1):
            print(f"\n{i}. {p['title']}")
            print(f"   Score: {p.get('relevancy_score','?')}% | Cached: {p.get('cached', False)}")
            print(f"   {p['summary']}")

        while True:
            try:
                choice = input(f"\nSelect (1-{len(papers)}) or q: ").strip()
                if choice.lower() == "q":
                    return
                idx = int(choice) - 1
                if 0 <= idx < len(papers):
                    selected = papers[idx]
                    break
            except ValueError:
                pass

        zip_bytes = self.generate_zip_bytes(selected)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in selected["title"]).replace(" ", "_")[:50]
        out = os.path.join(output_base_dir, f"{ts}_{safe}")
        os.makedirs(out, exist_ok=True)

        import zipfile as zf
        with zf.ZipFile(io.BytesIO(zip_bytes)) as z:
            z.extractall(out)

        print(f"\n✅ Repo extracted to: {out}")


def main():
    parser = argparse.ArgumentParser(description="Generate paper implementations from job descriptions")
    parser.add_argument("jd_file")
    parser.add_argument("--output-dir", default="./generated_repos")
    args = parser.parse_args()
    if not os.path.exists(args.jd_file):
        print(f"File not found: {args.jd_file}")
        return
    with open(args.jd_file) as f:
        jd = f.read()
    PaperToRepoAgent().run(jd, args.output_dir)


if __name__ == "__main__":
    main()
