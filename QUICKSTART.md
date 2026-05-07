# Quick Start Guide

## 5-Minute Setup

### 1. Get Your API Key
```bash
# Go to: https://console.anthropic.com/
# Create an account and generate an API key
```

### 2. Install
```bash
cd paper-to-repo-agent
pip install -r requirements.txt
```

### 3. Set API Key
```bash
# Option A: Environment variable (temporary)
export ANTHROPIC_API_KEY='sk-ant-...'

# Option B: .env file (persistent)
cp .env.example .env
# Edit .env and add your key
export $(cat .env | xargs)
```

### 4. Run
```bash
# Use the example JD
python agent.py example_jd.txt

# Or create your own
cat > my_jd.txt << 'EOF'
Paste your job description here
EOF

python agent.py my_jd.txt
```

## What You'll See

1. **Research areas extracted** - Agent identifies key topics from JD
2. **Papers found** - 3 recent papers ranked by relevance
3. **You select one** - Choose which to implement
4. **Code generated** - Complete repo created automatically
5. **Ready to run** - cd into directory, install deps, run code

## Example Run

```
$ python agent.py example_jd.txt

============================================================
🤖 PAPER-TO-REPO AGENT
============================================================

🔍 Analyzing job description...
   Found research areas: transformers, RLHF, efficient attention, multimodal learning, preference learning

📚 Searching for relevant papers...

   Found 3 papers:
   1. Flash Attention 2: Faster Attention with Better Parallelism
      Difficulty: Medium
   2. Direct Preference Optimization
      Difficulty: Medium
   3. LLaVA: Large Language and Vision Assistant
      Difficulty: Medium

------------------------------------------------------------
📋 SELECT A PAPER TO IMPLEMENT:
------------------------------------------------------------

1. Flash Attention 2: Faster Attention with Better Parallelism
   Authors: Tri Dao
   Summary: Improves attention speed with better GPU utilization
   Relevance: Directly related to efficient transformer variants
   To reproduce: Figure 3: attention speedup benchmarks
   Difficulty: Medium

Select paper (1-3) or 'q' to quit: 1

⚙️  Generating implementation for: Flash Attention 2...
   Output directory: ./generated_repos/20260506_120530_Flash_Attention_2
   ✅ Successfully generated 4 files
      - main.py
      - requirements.txt
      - README.md
      - benchmark.py

============================================================
✅ SUCCESS!
============================================================

Repo generated at: ./generated_repos/20260506_120530_Flash_Attention_2

Next steps:
1. cd ./generated_repos/20260506_120530_Flash_Attention_2
2. pip install -r requirements.txt
3. python main.py

📁 Push to GitHub when ready!
```

## Tips

**Finding Good JDs:**
- Look for research intern/engineer roles at: OpenAI, Anthropic, DeepMind, Meta FAIR, Microsoft Research
- Copy the entire JD text (including requirements and research areas)
- More detailed JDs = better paper matches

**Selecting Papers:**
- **Easy**: Good for day 1-3, quick wins
- **Medium**: Most common, 2-4 days typically
- **Hard**: 5-7+ days, complex math/large datasets

**After Generation:**
- Always read the generated README first
- Install deps in a virtual environment
- Expect to debug - generated code is a starting point
- Compare results with paper's reported numbers

**Debugging:**
- If no papers found: Make JD more specific about research areas
- If generation fails: Check API key, try again (Claude can be variable)
- If code doesn't run: Check requirements.txt, install missing deps

## Next Steps

1. **Generate 1-2 repos** to understand how it works
2. **Study the code** in `agent.py` - read all comments
3. **Modify prompts** to improve output quality
4. **Extend features** - add arXiv API, better ranking, etc.

## Cost

Each run uses ~4-6 API calls:
- ~$0.10-0.30 per paper implementation
- Depends on paper complexity and response length

For 10 papers: ~$1-3 total in API costs.

---

**You're ready! Run the agent and start building your portfolio. 🚀**
