"""远程触发 GitHub Actions Workflow（官方 REST API）。

文档:
  POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
  https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event

需要:
  1. 目标 workflow 已声明 workflow_dispatch
  2. Token：fine-grained PAT 需 Actions: Read and write；classic PAT 需 repo
     环境变量 GITHUB_TOKEN 或 GH_TOKEN（可写在 .env）

用法:
  uv run python trigger_workflow.py
  uv run python trigger_workflow.py --task sitemap
  uv run python trigger_workflow.py --task trends --wait
  uv run python trigger_workflow.py --list
"""

import argparse
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

API_VERSION = "2022-11-28"
DEFAULT_WORKFLOW = "sitemap-check.yml"
DEFAULT_REF = "main"
TASK_CHOICES = ("all", "sitemap", "trends")


class GitHubAPIError(RuntimeError):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def _token():
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    if not token:
        raise GitHubAPIError("未找到 Token：请设置环境变量 GITHUB_TOKEN 或 GH_TOKEN")
    return token


def _api_base():
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def _parse_repo(value):
    value = (value or "").strip()
    if not value:
        return None
    if value.count("/") != 1:
        raise argparse.ArgumentTypeError("仓库格式应为 owner/repo")
    owner, repo = value.split("/", 1)
    repo = repo.removesuffix(".git")
    if not owner or not repo:
        raise argparse.ArgumentTypeError("仓库格式应为 owner/repo")
    return f"{owner}/{repo}"


def _from_git_remote():
    try:
        raw = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if raw.startswith("git@"):
        # git@github.com:owner/repo.git
        match = re.search(r":([^/]+)/([^/]+?)(?:\.git)?$", raw)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        return None
    parsed = urlparse(raw)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return None


def resolve_repo(cli_repo):
    if cli_repo:
        return cli_repo
    env_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env_repo:
        return _parse_repo(env_repo)
    git_repo = _from_git_remote()
    if git_repo:
        return git_repo
    raise GitHubAPIError(
        "未指定仓库：传入 --repo owner/repo，或设置 GITHUB_REPOSITORY，或配置 git remote origin"
    )


def _headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "sitemap-monitor-trigger",
    }


def _session():
    # api.github.com（尤其 20.205.243.166/168）会偶发直接掐连接，重试即可。
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.8,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD", "POST"]),
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _request(method, path, token, **kwargs):
    url = f"{_api_base()}{path}"
    resp = _session().request(method, url, headers=_headers(token), timeout=30, **kwargs)
    if resp.status_code == 204:
        return None
    if not resp.ok:
        detail = resp.text.strip() or resp.reason
        hint = ""
        if resp.status_code == 404:
            hint = "（仓库/工作流不存在，或 Token 无权访问）"
        elif resp.status_code == 401:
            hint = "（Token 无效或已过期）"
        elif resp.status_code == 403:
            hint = "（权限不足：需要 Actions write）"
        elif resp.status_code == 422:
            hint = "（ref 不存在，或该 workflow 未声明 workflow_dispatch / inputs 不合法）"
        raise GitHubAPIError(
            f"GitHub API {resp.status_code} {method} {path}: {detail}{hint}",
            status=resp.status_code,
            body=detail,
        )
    if not resp.content:
        return None
    return resp.json()


def dispatch_workflow(owner_repo, workflow, ref, inputs, token):
    """POST .../actions/workflows/{id}/dispatches，成功返回 204。"""
    _request(
        "POST",
        f"/repos/{owner_repo}/actions/workflows/{workflow}/dispatches",
        token,
        json={"ref": ref, "inputs": inputs},
    )


def list_runs(owner_repo, workflow, token, per_page=10, event=None):
    params = {"per_page": per_page}
    if event:
        params["event"] = event
    data = _request(
        "GET",
        f"/repos/{owner_repo}/actions/workflows/{workflow}/runs",
        token,
        params=params,
    )
    return data.get("workflow_runs", []) if data else []


def find_new_run(owner_repo, workflow, ref, token, seen_ids, timeout=60, interval=2):
    """dispatch 不返回 run id，轮询最近的 workflow_dispatch 找出新 run。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for run in list_runs(owner_repo, workflow, token, per_page=5, event="workflow_dispatch"):
            if run.get("id") in seen_ids:
                continue
            if run.get("head_branch") == ref:
                return run
        time.sleep(interval)
    return None


def _print_run(run):
    run_id = run.get("id")
    status = run.get("status")
    conclusion = run.get("conclusion") or "-"
    created = run.get("created_at")
    html = run.get("html_url")
    event = run.get("event")
    branch = run.get("head_branch")
    logging.info(
        f"run {run_id}  {status}/{conclusion}  {event}@{branch}  {created}\n  {html}"
    )


def main():
    parser = argparse.ArgumentParser(description="远程触发 GitHub Actions Workflow")
    parser.add_argument(
        "--repo",
        type=_parse_repo,
        help="仓库 owner/repo（默认同 GITHUB_REPOSITORY 或 git origin）",
    )
    parser.add_argument(
        "--workflow",
        default=DEFAULT_WORKFLOW,
        help=f"工作流文件名或 ID（默认 {DEFAULT_WORKFLOW}）",
    )
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"分支 / tag / SHA（默认 {DEFAULT_REF}）",
    )
    parser.add_argument(
        "--task",
        choices=TASK_CHOICES,
        default="all",
        help="Monitor 的 inputs.task：all / sitemap / trends（默认 all）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="只列出最近几次运行，不触发",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="触发后轮询，打印新 run 的网页地址",
    )
    args = parser.parse_args()

    try:
        token = _token()
        owner_repo = resolve_repo(args.repo)
    except (GitHubAPIError, argparse.ArgumentTypeError) as e:
        logging.error(str(e))
        return 1

    try:
        if args.list:
            runs = list_runs(owner_repo, args.workflow, token)
            if not runs:
                logging.info(f"{owner_repo} / {args.workflow}：暂无运行记录")
                return 0
            logging.info(f"{owner_repo} / {args.workflow} 最近 {len(runs)} 次运行：")
            for run in runs:
                _print_run(run)
            return 0

        seen = set()
        if args.wait:
            seen = {r.get("id") for r in list_runs(owner_repo, args.workflow, token, per_page=5)}
        inputs = {"task": args.task}
        logging.info(
            f"触发 {owner_repo} / {args.workflow}  ref={args.ref}  inputs={inputs}"
        )
        dispatch_workflow(owner_repo, args.workflow, args.ref, inputs, token)
        logging.info("已提交 workflow_dispatch（API 返回 204）")

        if not args.wait:
            logging.info("加 --wait 可查出本次 run 链接；或打开仓库 Actions 页查看")
            return 0

        run = find_new_run(owner_repo, args.workflow, args.ref, token, seen)
        if not run:
            logging.warning("已触发，但在超时时间内未找到新 run，请到 Actions 页确认")
            return 0
        _print_run(run)
        return 0
    except requests.RequestException as e:
        logging.error(
            f"连不上 GitHub API（{e}）。token 已读到，是 HTTPS 被对端掐断，可重试一次；"
            f"若持续失败再检查代理 / GITHUB_API_URL"
        )
        return 1
    except GitHubAPIError as e:
        logging.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
