"""
push_to_github.py — Push committed changes to GitHub repository using pure-Python dulwich.
Supports GitHub Personal Access Token (PAT).
"""
import os
import sys

def main():
    token = os.getenv("GITHUB_TOKEN")
    if len(sys.argv) > 1:
        token = sys.argv[1]

    if not token:
        print("=" * 60)
        print("GitHub Authentication Required to Push:")
        print("Please provide a GitHub Personal Access Token (PAT) with 'repo' scope.")
        print("Usage:")
        print("  .\\.venv\\Scripts\\python.exe tools\\push_to_github.py <YOUR_GITHUB_TOKEN>")
        print("Or set it in environment:")
        print("  $env:GITHUB_TOKEN = '<YOUR_GITHUB_TOKEN>'")
        print("  .\\.venv\\Scripts\\python.exe tools\\push_to_github.py")
        print("=" * 60)
        sys.exit(1)

    try:
        from dulwich import porcelain
        remote_url = f"https://Shivendra2021:{token}@github.com/Shivendra2021/-intraday-stock-screener.git"
        print("Pushing commit 34a6a6c to https://github.com/Shivendra2021/-intraday-stock-screener.git (branch main)...")
        porcelain.push(".", remote_url, "refs/heads/main")
        print("✅ PUSH SUCCESSFUL! GitHub Actions workflow is now live in the cloud.")
    except Exception as exc:
        print("❌ Push failed:", exc)
        sys.exit(1)

if __name__ == "__main__":
    main()
