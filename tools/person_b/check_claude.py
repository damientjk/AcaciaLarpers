"""Make one small Claude API request. Never saves or prints the API key."""

from __future__ import annotations

import argparse
import getpass
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
    )
    parser.add_argument(
        "--prompt-key", action="store_true", help="Enter a key privately for this run only."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Check settings without sending any request."
    )
    args = parser.parse_args()
    if args.dry_run:
        print(f"Model: {args.model}; output limit: 256 tokens; timeout: 20s; retries: 0.")
        print("No API request sent. No credits used.")
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if args.prompt_key:
        if not sys.stdin.isatty():
            print("Use --prompt-key from your own interactive terminal.", file=sys.stderr)
            return 2
        try:
            key = getpass.getpass("Anthropic API key (hidden; not saved): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled. No request sent.", file=sys.stderr)
            return 2
    if not key:
        print(
            "No API key configured. Run with --prompt-key, or set ANTHROPIC_API_KEY.",
            file=sys.stderr,
        )
        return 2

    try:
        import anthropic
    except ImportError:
        print(
            "Install the official SDK: python -m pip install anthropic", file=sys.stderr
        )
        return 2

    try:
        with anthropic.Anthropic(api_key=key, timeout=20.0, max_retries=0) as client:
            request = {
                "model": args.model,
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "Reply with exactly API_OK."}],
            }
            if args.model == "claude-haiku-5-5":
                request["thinking"] = {"type": "disabled"}
            message = client.messages.create(**request)
    except anthropic.AuthenticationError:
        print("Authentication failed. Check your Claude Console API key.", file=sys.stderr)
        return 1
    except anthropic.PermissionDeniedError:
        print("The key lacks access. Check project permissions and model access.", file=sys.stderr)
        return 1
    except anthropic.RateLimitError:
        print("A rate or spending limit was reached. Check Claude Console usage.", file=sys.stderr)
        return 1
    except anthropic.APITimeoutError:
        print("The request timed out after 20 seconds. No retry was sent.", file=sys.stderr)
        return 1
    except anthropic.APIConnectionError:
        print("Could not reach Anthropic. Check your network connection.", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as error:
        print(
            f"Claude returned HTTP {error.status_code}. Check model access, billing and request settings.",
            file=sys.stderr,
        )
        return 1

    text = "".join(block.text for block in message.content if block.type == "text").strip()
    print(f"Reply: {text or '(no text returned)'}")
    print(f"Input tokens: {message.usage.input_tokens}; output tokens: {message.usage.output_tokens}.")
    print(f"Model: {message.model}; stop reason: {message.stop_reason}.")
    return 0 if text == "API_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
