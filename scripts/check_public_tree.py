"""Fail closed before publishing: public code only; project artifacts live elsewhere."""
from pathlib import Path
import argparse,subprocess,re,sys

ROOT=Path(__file__).resolve().parent.parent
EXTENSIONS={'.py','.js','.css','.html','.md','.toml','.yml','.yaml','.txt','.ps1'}
SPECIAL={'.gitignore','.env.example','LICENSE'}
SECRETS=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'gh[pousr]_[A-Za-z0-9]{25,}',rb'sk-(?:proj-)?[A-Za-z0-9_-]{35,}']

def scan(paths,deny=()):
    errors=[]
    for name in paths:
        path=ROOT/name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):errors.append(name+': link/outside checkout');continue
        if path.name not in SPECIAL and path.suffix.lower() not in EXTENSIONS:errors.append(name+': non-source file type');continue
        if any(p.lower() in {'uploads','projects','data','exports','outputs','logs','work','.venv'} for p in Path(name).parts):errors.append(name+': private/generated directory');continue
        data=path.read_bytes()
        if len(data)>600000 or b'\x00' in data:errors.append(name+': binary or unexpectedly large');continue
        if any(re.search(pattern,data) for pattern in SECRETS):errors.append(name+': possible credential');continue
        text=data.decode('utf-8').lower()
        if re.search(r'[a-z]:[\\/]+users[\\/]+',text):errors.append(name+': personal absolute path')
        if any(term.strip().lower() in text for term in deny if term.strip()):errors.append(name+': private deny-list match')
    return errors

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--deny-file',type=Path);args=p.parse_args()
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().strip('\0').split('\0')
    deny=args.deny_file.read_text(encoding='utf-8').splitlines() if args.deny_file else []
    errors=scan(paths,deny)
    if errors:print('\n'.join(errors));sys.exit(1)
    print(f'Public tree check passed: {len(paths)} source files; no client artifacts or credentials detected.')
