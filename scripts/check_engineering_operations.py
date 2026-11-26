"""Exercise registered CAD operations through Harness host capability layer."""
from pathlib import Path
import argparse
import json
from harness2.host_capabilities import execute

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    calls=[("openscad_make_primitive",{"shape":"cube","size_mm":2,"height_mm":2}),
           ("scilab_batch_smoke_test",{}),("freecad_python_api_smoke_test",{}),
           ("eda_project_registry",{})]
    results=[]
    for name,parameters in calls:
        try:
            value=execute("mcp_call",{"server":"eda" if name.startswith("eda_") else "cad",
                                    "tool":name,"arguments":parameters})
        except Exception as exc:
            value={"operation_status":"failed","error":str(exc)[:500]}
        results.append({"tool":name,"reply":value})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(results,ensure_ascii=False))
if __name__=="__main__":
    main()
