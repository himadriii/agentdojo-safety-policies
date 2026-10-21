"""Repository-local .env configuration shared by every branch's runner."""
import argparse
from pathlib import Path

from dotenv import load_dotenv

from agent_framework.inference import PROVIDERS, check_local_models, component_settings, resolve_model

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_runner_env():
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    args, _ = preliminary.parse_known_args()
    if not args.env_file.is_file() and args.env_file != REPO_ROOT / ".env":
        preliminary.error(f"Configuration file does not exist: {args.env_file}")
    # A checked-out branch reads its own .env, regardless of the launch directory.
    # Values deliberately set in that file take precedence over inherited values.
    load_dotenv(args.env_file, override=True)
    return args.env_file


def validate_inference_args(parser, args, *, providers=PROVIDERS, has_provenance=False):
    try:
        args.llm = resolve_model(args.provider, args.llm)
        selected = [(args.provider, args.llm)]
        if has_provenance and args.policy == "provenance":
            selected.append(component_settings("PROVENANCE", args.provider, args.llm))
        if args.reviewer in ("llm", "local_llm"):
            selected.append(component_settings("REVIEWER", args.provider, args.llm, args.reviewer_model))
        for provider, _ in selected:
            if provider not in providers:
                raise ValueError(f"Provider {provider!r} is not supported on this branch.")
        check_local_models([model for provider, model in selected if provider == "lmstudio"])
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
