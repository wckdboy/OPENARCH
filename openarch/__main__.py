import argparse
import uvicorn

def main():
    parser = argparse.ArgumentParser(description="Run the local balcony workspace")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run("openarch.server:app", host="127.0.0.1", port=args.port, workers=1)

if __name__ == "__main__":
    main()
