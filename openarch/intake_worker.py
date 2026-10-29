"""Keep native PDF decoders in a child process, away from the local web server."""
import sys
from .intake import ingest
from .storage import valid_id

if __name__=='__main__':
    ingest(valid_id(sys.argv[1]))
    print('INTAKE_COMPLETE',flush=True)
