# 🤖 Autonomous Paper-to-Repo Agent

An autonomous AI agent that reads AI/ML job descriptions, identifies the most relevant frontier research papers, and writes complete, runnable Python implementations for them.

Built to automate the transition from academic research to applied engineering.

**🌐 Live Demo:** [https://paper-to-repo-agent.onrender.com/](https://paper-to-repo-agent.onrender.com/)

---

## 🎯 What it does

Instead of manually scraping arXiv or guessing what skills a research lab is looking for, this agent automates the entire discovery and implementation pipeline.

You provide a job description. The agent:
1. Performs **Chain-of-Thought (CoT) reasoning** to extract the core mathematical and architectural requirements of the role.
2. Queries the **Semantic Scholar API** to find highly-cited, relevant papers (2023-2025).
3. **Ranks** the papers by relevancy score, sorted from highest to lowest, with links guaranteed.
4. **Reads the Full Paper:** Downloads the actual PDF from arXiv and extracts the text using PyMuPDF, intelligently stripping out References and Acknowledgments sections to maximize token efficiency.
5. **Writes the code** (Main logic, Requirements, Documentation) by injecting the full paper context directly into the LLM prompt, guaranteeing architectural accuracy.
6. Employs a **Self-Refinement Loop** to review its own code and fix bugs.
7. Runs the code in an **Execution Sandbox** to verify functionality.
8. **Quality Benchmarks** the generated code with an automated A-D grading system.
9. Packages the result into a downloadable `.zip` or pushes it directly to **GitHub**.

## 🧠 Engineering Architecture

This project demonstrates advanced LLM orchestration, moving beyond simple chat interfaces into autonomous, multi-step agentic workflows.

- **Agentic Workflow:** An 11-step pipeline utilizing LLMs for reasoning, ranking, reading, writing, and self-correction.
- **Long-Context RAG:** Bypasses traditional chunked Vector DBs by extracting full academic PDFs (via PyMuPDF) and injecting the complete methodology directly into the massive 128k context window of Llama 3.3.
- **Smart Token Saver:** Automatically strips References, Bibliography, and Acknowledgments sections from PDFs before injection — cutting wasted tokens by up to 40% and maximizing the budget for actual methodology.
- **Resilient Multi-Key Rotation:** Supports multiple Groq API keys from independent accounts. On every LLM call, it randomly selects a key. If one hits a rate limit (429/413), it automatically switches to the next available key without any user intervention.
- **Self-Refinement:** The agent is prompted to act as its own critic, catching missing imports or logic errors before the user ever sees the code.
- **Execution Sandboxing:** Code is spawned in a temporary subprocess. `stdout`/`stderr` and return codes are captured to generate a real-world pass/fail quality benchmark.
- **Asynchronous SSE Streaming:** The Flask backend streams real-time execution progress to the frontend via Server-Sent Events (SSE).
- **Intelligent Caching:** Paper generation results are hashed (SHA-256) and cached locally via SQLite to eliminate redundant LLM calls and API latency.
- **Zero-Cost Scalability:** Powered entirely by free-tier APIs (Groq Llama 3.3 70B, Semantic Scholar).

## 🚀 Tech Stack

- **Backend:** Python, Flask, Gunicorn
- **AI/LLM:** Groq API (Llama 3.3 70B Versatile) with multi-key rotation
- **Data Integration:** Semantic Scholar API, DuckDuckGo Search, arXiv PDF Retrieval, GitHub REST API
- **Infrastructure:** SQLite, PyMuPDF (Text Extraction), Subprocess Sandboxing, SSE (Server-Sent Events)

---

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.8+
- [Groq API Key](https://console.groq.com/) (Free — use keys from separate accounts for higher daily limits)

### Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Debmalya0132/paper-to-repo-agent.git
   cd paper-to-repo-agent
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   Create a `.env` file in the root directory:
   ```env
   # Comma-separated keys from independent Groq accounts for maximum daily quota
   GROQ_API_KEYS=gsk_key1_from_email1,gsk_key2_from_email2,gsk_key3_from_email3

   # Optional: For GitHub Auto-Push feature
   GITHUB_USERNAME=your_username
   GITHUB_TOKEN=ghp_your_personal_access_token_with_repo_scope
   ```

4. **Run the application:**
   ```bash
   PORT=8080 python app.py
   ```
   Open your browser and navigate to `http://localhost:8080`.

## 🌐 Production Deployment

This application is configured for seamless deployment to platforms like Render or Heroku.

- **Render:** Connect the repository and use the provided `render.yaml` blueprint. The service will automatically configure Gunicorn as the WSGI server via the `Procfile`.
- **Environment Variables:** In the Render dashboard, add `GROQ_API_KEYS` (comma-separated) and optionally `GITHUB_TOKEN` and `GITHUB_USERNAME`.

## 📂 File Structure

```
.
├── agent.py               # Core LLM orchestration, sandboxing, and GitHub integration
├── app.py                 # Flask server handling REST endpoints and SSE streams
├── templates/
│   └── index.html         # Vanilla JS frontend with real-time UI updates
├── requirements.txt       # Dependencies
├── render.yaml            # Render deployment blueprint
├── Procfile               # Production WSGI command (120s timeout)
└── papers.db              # SQLite cache database (auto-generated)
```

---

## 🔭 Potential Improvements (Future Goals)

1. **Error Recovery** — If sandbox execution fails, feed the error back to the LLM for another refinement iteration instead of stopping.
2. **Multi-Model Ensemble** — Use different models for different steps (fast model for ranking, powerful model for code generation).
3. **Batch Processing** — Queue multiple papers and run implementations in parallel.
4. **Code Quality Metrics** — Run `pylint` / `black` on generated code automatically before packaging the zip.
5. **Test Generation** — Auto-generate unit tests alongside `main.py` for each paper implementation.
6. **Paper Comparison** — Let the user select multiple papers; the agent generates a structured comparison table of architectures and results.
