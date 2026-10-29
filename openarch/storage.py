"""Private project storage, deliberately separate from the public code checkout."""
from pathlib import Path
import os, json, uuid, threading, copy
from datetime import datetime, timezone

LOCK = threading.RLock()
REPO = Path(__file__).resolve().parent.parent

def data_root() -> Path:
    default = Path(os.environ.get("LOCALAPPDATA", Path.home()/".local"/"share"))/"OPENARCH"
    root = Path(os.environ.get("OPENARCH_DATA_DIR", default)).expanduser().resolve()
    if root == REPO or REPO in root.parents:
        raise RuntimeError("OPENARCH_DATA_DIR must be outside the code checkout")
    root.mkdir(parents=True, exist_ok=True)
    return root

def valid_id(value: str) -> str:
    if str(uuid.UUID(value)) != value:
        raise ValueError("Invalid project ID")
    return value

def folder(pid: str) -> Path:
    p = data_root()/valid_id(pid)
    if not p.is_dir():
        raise FileNotFoundError("Project not found")
    return p

def now():
    return datetime.now(timezone.utc).isoformat()

def atomic(path: Path, value):
    tmp = path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def create(name: str):
    from .schema import ModelSpec
    pid = str(uuid.uuid4());p=data_root()/pid;p.mkdir()
    (p/"sources").mkdir();(p/"pages").mkdir();(p/"runs").mkdir()
    state={"id":pid,"name":name,"created_at":now(),"revision":0,"status":"empty","files":[],"pages":[],"spec":ModelSpec().model_dump(),"events":[],"runs":[],"busy":False}
    atomic(p/"project.json",state)
    return state

def read(pid):
    with LOCK:
        return json.loads((folder(pid)/"project.json").read_text(encoding="utf-8"))

def mutate(pid, fn):
    with LOCK:
        s=read(pid);fn(s);s["updated_at"]=now();atomic(folder(pid)/"project.json",s);return s

def event(pid, stage, message):
    def update(s):
        s["status"]=stage;s["events"].append({"at":now(),"stage":stage,"message":message});s["events"]=s["events"][-200:]
    return mutate(pid,update)

def acquire(pid):
    with LOCK:
        s=read(pid)
        if s["busy"]:raise ValueError("A job is already running for this project")
        mutate(pid,lambda x:x.update(busy=True))

def release(pid):
    mutate(pid,lambda x:x.update(busy=False))

def safe_file(pid, area, name):
    if area not in {"sources","pages"}:raise ValueError("Invalid file area")
    if Path(name).name != name or "/" in name or "\\" in name:raise ValueError("Invalid file name")
    root=folder(pid)/area;p=(root/name).resolve()
    if p.parent != root.resolve() or not p.is_file():raise FileNotFoundError()
    return p

def recover_interrupted():
    for p in data_root().glob("*/project.json"):
        s=json.loads(p.read_text(encoding="utf-8"))
        if s.get("busy"):
            s.update(busy=False,status="interrupted")
            s["events"].append({"at":now(),"stage":"interrupted","message":"Application stopped during a job. Run it again."})
            atomic(p,s)
