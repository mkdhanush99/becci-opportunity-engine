#!/usr/bin/env python3
"""Minimal Sarvam AI integration milestone script.

Complies with Master Autonomous Build Directive Section 11:
- Uses official sarvamai Python SDK
- Reads SARVAM_API_KEY from environment / .env
- Uses model: sarvam-105b-conversations
- Never contains dummy or compromised keys
- Stops and prompts the owner to paste replacement key into .env
"""
import os
import sys
from pathlib import Path


def load_env_file():
    """Load key-value pairs from .env in project root if present."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and v and k not in os.environ:
                        os.environ[k] = v


def main():
    load_env_file()
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()

    if not api_key:
        print("\n" + "=" * 60)
        print("SARVAM AI MILESTONE — PENDING REPLACEMENT KEY")
        print("=" * 60)
        print("SARVAM_API_KEY is currently empty in .env.")
        print("As required by security guidelines:")
        print("Please paste your replacement Sarvam API key into:")
        print("  /Users/dhanushmakam/.gemini/antigravity/scratch/becci-opportunity-engine/.env")
        print("  SARVAM_API_KEY=<your-replacement-key>")
        print("Then run:")
        print("  .venv/bin/python3 scripts/sarvam_test.py")
        print("=" * 60 + "\n")
        return 0

    try:
        from sarvamai import SarvamAI
    except ImportError:
        print("Error: sarvamai package not installed. Run: pip install sarvamai")
        return 1

    print("Initializing Sarvam AI client with model 'sarvam-105b-conversations'...")
    client = SarvamAI(api_subscription_key=api_key)

    try:
        response = client.chat.completions(
            model="sarvam-105b-conversations",
            messages=[
                {"role": "user", "content": "Hello! Explain BECCI opportunity intelligence in one sentence."}
            ]
        )
        print("\n--- Sarvam AI Reply ---")
        if hasattr(response, "choices") and response.choices:
            print(response.choices[0].message.content)
        else:
            print(response)
        print("-----------------------\n")
        return 0
    except Exception as exc:
        print(f"Sarvam API call failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
