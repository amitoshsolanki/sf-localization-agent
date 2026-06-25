import argparse
import asyncio
import os
import pathlib
import uuid

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Salesforce UI Localization Agent")
    parser.add_argument("--input", required=True, help="Path to the Salesforce .stf translation file")
    parser.add_argument("--target-language", default="", help="ISO 639-1 target language code (auto-detected from file if omitted)")
    parser.add_argument("--output", default=None, help="Output file path (default: <input>.<lang>.stf)")
    args = parser.parse_args()

    input_path = pathlib.Path(args.input).resolve()

    from app.db.session import create_tables, DATABASE_URL
    from app.graph import build_graph

    await create_tables()

    pg_conn_str = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    checkpointer = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        import psycopg  # noqa: F401
        checkpointer_ctx = AsyncPostgresSaver.from_conn_string(pg_conn_str)
        checkpointer = await checkpointer_ctx.__aenter__()
        await checkpointer.setup()
    except ImportError:
        print("psycopg3 not found — running without LangGraph checkpoint persistence.")

    try:
        graph = build_graph(checkpointer)

        initial_state = {
            "input_file_path": str(input_path),
            "target_language": args.target_language or "",
            "segments": [],
            "stf_lines": [],
            "translation_col": -1,
            "glossary_context": "[]",
            "translated_segments": [],
            "glossary_violations": [],
            "failed_segment_ids": [],
            "loop_count": 0,
            "validation_issues": [],
            "output_stf": None,
            "extracted_glossary_count": 0,
            "errors": [],
        }

        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = await graph.ainvoke(initial_state, config=config)

        if result.get("errors"):
            print("Errors encountered:")
            for err in result["errors"]:
                print(f"  - {err}")

        if result.get("glossary_violations"):
            print(f"Unresolved glossary violations ({len(result['glossary_violations'])}):")
            for v in result["glossary_violations"]:
                print(f'  - {v["segment_id"]}: expected "{v["approved_translation"]}" for "{v["source_term"]}"')

        if result.get("validation_issues"):
            print(f"Validation issues ({len(result['validation_issues'])}):")
            for issue in result["validation_issues"]:
                print(f"  [{issue['issue_type']}] {issue['segment_id']}: {issue['details']}")

        if result.get("output_stf"):
            target_lang = result.get("target_language", args.target_language or "out")
            output_path = pathlib.Path(args.output).resolve() if args.output else input_path.with_suffix(f".{target_lang}.stf")
            output_path.write_text(result["output_stf"], encoding="utf-8")
            print(f"Output written to: {output_path}")
            if result.get("extracted_glossary_count", 0) > 0:
                print(f"Auto-extracted {result['extracted_glossary_count']} glossary term(s) (unapproved)")
        else:
            print("No output produced — check errors and issues above.")
    finally:
        if checkpointer is not None:
            try:
                await checkpointer_ctx.__aexit__(None, None, None)
            except Exception:
                pass


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
