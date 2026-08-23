import argparse
import json
import eve_openclaw_body

def cmd_openclaw_admission_list(args: argparse.Namespace) -> int:
    records = eve_openclaw_body.read_admission_records(limit=args.limit, prefer_runtime=args.runtime)
    if args.json:
        print(json.dumps({"records": records}, indent=2, ensure_ascii=True))
    else:
        print(eve_openclaw_body.format_admission_records(records, full=args.full))
    return 0


def cmd_openclaw_admission_create(args: argparse.Namespace) -> int:
    record = eve_openclaw_body.create_admission_record(
        candidate_id=args.candidate_id,
        candidate_type=args.candidate_type,
        source=args.source,
        capability=args.capability,
        permission_level=args.permission_level,
        data_boundary=args.data_boundary,
        decision=args.decision,
        verification_command=args.verification_command or "",
        rollback=args.rollback or "",
        notes=args.notes or "",
    )
    if args.json:
        print(json.dumps(record, indent=2, ensure_ascii=True))
    else:
        print(eve_openclaw_body.format_admission_records([record], full=True))
    return 0
