#!/usr/bin/env python3
"""
Deployment validator for Pickwatch Dashboard.
Run before deploying to Coolify.
"""

import os
import sys

def check_file(path, required=True):
    """Check file exists."""
    exists = os.path.exists(path)
    status = "✅" if exists else ("❌" if required else "⚠️")
    req = "required" if required else "optional"
    print(f"{status} {path} ({req})")
    return exists or not required

def check_dockerfile():
    """Verify Dockerfile syntax."""
    with open("Dockerfile") as f:
        content = f.read()
    
    checks = [
        ("FROM python:3.11-slim" in content, "Uses Python 3.11 slim"),
        ("WORKDIR /app" in content, "Sets workdir"),
        ("EXPOSE 8080" in content, "Exposes port 8080"),
        ("HEALTHCHECK" in content, "Has healthcheck"),
        ("server.py" in content, "Runs server.py"),
    ]
    
    ok = True
    for check, desc in checks:
        status = "✅" if check else "❌"
        print(f"  {status} {desc}")
        ok = ok and check
    return ok

def main():
    print("🔍 Pickwatch Dashboard Deployment Validation\n")
    
    checks = [
        ("Dockerfile", True),
        ("docker-compose.yml", True),
        ("requirements.txt", True),
        ("server.py", True),
        ("api_client.py", True),
        ("scoring.py", True),
        ("DEPLOY-COOLIFY.md", True),
        ("DEPLOY.md", False),
    ]
    
    all_ok = True
    print("📁 Files:")
    for file, req in checks:
        if not check_file(file, req):
            all_ok = False
    
    print("\n🐳 Dockerfile checks:")
    if not check_dockerfile():
        all_ok = False
    
    print("\n📦 Deployment status:")
    if all_ok:
        print("🟢 READY for Coolify deployment")
        print("\nNext steps:")
        print("  1. Push to GitHub repo")
        print("  2. Create Docker Compose resource in Coolify")
        print("  3. Set PICKWATCH_TOKEN environment variable")
        print("  4. Deploy")
        return 0
    else:
        print("🔴 NOT READY - fix issues above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
