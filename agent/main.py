# agent/main.py
#
# Entry point for the Oman Real Estate conversational agent.
# Run this to start a chat session in your terminal:
#
#   python -m agent.main
#
# Prerequisites:
#   1. Run the scraper:  python -m scraper.runner
#   2. Run the cleaner:  python -m scraper.data_cleaner
#   3. Set your API key: export ANTHROPIC_API_KEY=your_key
#      (or copy .env.example to .env and fill it in)
#
# How this works:
#   - We load the cleaned listings into memory.
#   - We start a chat loop: user types → we send to Claude → Claude may call
#     tools → we execute them → Claude writes a final answer.
#   - The conversation history is kept in a list and sent to Claude each turn
#     so it has context from earlier in the conversation.

import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on the Python path when running as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from dotenv import load_dotenv

from config.settings import CLEAN_DATA_FILE, CLAUDE_MODEL, MAX_TOKENS, ANTHROPIC_API_KEY
from agent.prompts import SYSTEM_PROMPT
from agent.tools   import TOOL_DEFINITIONS, dispatch_tool, load_listings

# ─── Setup ────────────────────────────────────────────────────────────────────

load_dotenv()  # loads .env file if present (ANTHROPIC_API_KEY etc.)

logging.basicConfig(
    level=logging.WARNING,   # only show warnings+ in the terminal during chat
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("agent")

BANNER = """
=======================================================
       Oman Real Estate Agent -- Muscat Market
  Type your question. Type 'quit' or 'exit' to leave.
=======================================================
"""

# ─── Agent loop ───────────────────────────────────────────────────────────────

def run_agent_turn(
    client:      anthropic.Anthropic,
    messages:    list[dict],
) -> str:
    """
    Send the current conversation to Claude and handle any tool calls.

    This function implements the "agentic loop":
      1. Call Claude.
      2. If Claude wants to use a tool (stop_reason == "tool_use"):
         a. Execute each requested tool.
         b. Append the tool results to the message history.
         c. Call Claude again with the new history.
         d. Repeat until Claude gives a text response.
      3. Return Claude's final text response.

    We cap iterations at 5 to avoid infinite loops in edge cases.
    """
    MAX_ITERATIONS = 5

    for iteration in range(MAX_ITERATIONS):
        response = client.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = MAX_TOKENS,
            system     = SYSTEM_PROMPT,
            tools      = TOOL_DEFINITIONS,
            messages   = messages,
        )

        # ── Case 1: Claude is done — return its text ──────────────────────────
        if response.stop_reason == "end_turn":
            # Extract text content from the response.
            text_parts = [
                block.text
                for block in response.content
                if hasattr(block, "text")
            ]
            return "\n".join(text_parts)

        # ── Case 2: Claude wants to call one or more tools ────────────────────
        if response.stop_reason == "tool_use":
            # Add Claude's response (which includes the tool_use blocks) to history.
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool call and collect results.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                logger.info(f"Tool call: {block.name}({block.input})")
                result = dispatch_tool(block.name, block.input)

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result, ensure_ascii=False, default=str),
                })

            # Add all tool results as a single user message.
            messages.append({"role": "user", "content": tool_results})

            # Loop back — Claude will read the results and continue.
            continue

        # ── Unexpected stop reason ────────────────────────────────────────────
        logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
        break

    return "Sorry, I ran into an issue processing that request. Please try again."


def main():
    # ── Check API key ──────────────────────────────────────────────────────────
    api_key = os.getenv("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        print("Set it with:  export ANTHROPIC_API_KEY=your_key")
        print("Or copy .env.example to .env and fill in your key.")
        sys.exit(1)

    # ── Load data ──────────────────────────────────────────────────────────────
    print("Loading listings …", end=" ", flush=True)
    listings = load_listings(str(CLEAN_DATA_FILE))
    if not listings:
        print()
        print(f"WARNING: No listings found in {CLEAN_DATA_FILE}")
        print("Run the scraper first:  python -m scraper.runner")
        print("Then the cleaner:       python -m scraper.data_cleaner")
        print("Continuing anyway — you can still ask questions, but answers will be empty.")
    else:
        print(f"{len(listings)} listings loaded.")

    # ── Init Claude client ─────────────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)

    print(BANNER)

    # ── Chat loop ──────────────────────────────────────────────────────────────
    # We maintain a running list of messages. Each turn we append the user
    # message and then the assistant response (+ any tool calls/results).
    messages: list[dict] = []

    while True:
        # Get user input.
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "bye", "q"):
            print("Goodbye!")
            break

        # Add the user's message to the conversation history.
        messages.append({"role": "user", "content": user_input})

        # Get Claude's response (may involve tool calls internally).
        try:
            reply = run_agent_turn(client, messages)
        except anthropic.APIStatusError as e:
            print(f"\nAPI error: {e.status_code} — {e.message}\n")
            # Remove the user message we just added so the history stays clean.
            messages.pop()
            continue
        except Exception as e:
            print(f"\nUnexpected error: {e}\n")
            messages.pop()
            continue

        # Add Claude's final text reply to history and display it.
        messages.append({"role": "assistant", "content": reply})
        print(f"\nAgent: {reply}\n")


if __name__ == "__main__":
    main()
