"""Meshy adapter. A paid submission is never retried automatically.

Live account validation is required before production use. No calls are made
without a configured key AND per-job third-party processing consent.
"""

import base64
import ipaddress
import os
import socket
import time
from urllib.parse import urlparse

import httpx


class SubmissionUnknown(Exception):
    pass


class RemotePending(Exception):
    pass


class Cancelled(Exception):
    pass


def checked_public_url(url):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("供应商返回了不允许的下载地址")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("不允许从本地或私有网络下载模型")
    return url


def download_model(url, destination):
    """Downloads public HTTPS only; inspect every redirect and bound file size."""
    with httpx.Client(timeout=60, trust_env=False) as client:
        for _ in range(4):
            checked_public_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    from urllib.parse import urljoin

                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                total = 0
                temporary = destination.with_suffix(".partial")
                try:
                    with temporary.open("wb") as output:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > 150 * 1024 * 1024:
                                raise ValueError("模型超过 150 MB 下载上限")
                            output.write(chunk)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
                return
    raise ValueError("供应商下载重定向过多")


def generate_meshy(store, job_id, prepared, destination):
    job = store.job(job_id)
    task_id = job.get("provider_task_id")
    headers = {"Authorization": "Bearer " + os.environ["MESHY_API_KEY"]}
    with httpx.Client(base_url="https://api.meshy.ai/openapi/v1/", headers=headers, timeout=40) as client:
        if not task_id:
            if job.get("submission_started"):
                raise SubmissionUnknown("上次云端提交状态不确定，请到供应商后台核对；系统不会自动再次扣费")
            data = prepared.read_bytes()
            if len(data) > 9 * 1024 * 1024:
                raise ValueError("处理后的 PNG 超过 9 MB，请缩小图片后再使用云端生成")
            store.update(job_id, lambda item: item.update(submission_started=True))
            if store.job(job_id)["status"] == "cancelled":
                raise Cancelled()
            payload = {"image_url": "data:image/png;base64," + base64.b64encode(data).decode(), "enable_pbr": True}
            if os.getenv("MESHY_AI_MODEL"):
                payload["ai_model"] = os.environ["MESHY_AI_MODEL"]
            try:
                response = client.post("image-to-3d", json=payload)
            except httpx.TransportError as exc:
                raise SubmissionUnknown("云端提交连接中断，请核对供应商后台；不会自动重复提交") from exc
            if response.status_code >= 500:
                raise SubmissionUnknown("供应商提交响应异常，无法确认是否已创建付费任务，请核对后台")
            if response.status_code >= 400:
                raise ValueError("云端拒绝请求（HTTP %s），请检查账号、额度和模型配置" % response.status_code)
            try:
                task_id = response.json()["result"]
                if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
                    raise ValueError()
            except (KeyError, ValueError, TypeError) as exc:
                raise SubmissionUnknown("供应商返回了无法识别的提交结果，请核对后台") from exc
            # Persist even if cancellation won the race: the remote task may be billed.
            store.update(job_id, lambda item: item.update(provider_task_id=task_id), allow_cancelled=True)
        start, failures = time.monotonic(), 0
        while time.monotonic() - start < 1200:
            if store.job(job_id)["status"] == "cancelled":
                raise Cancelled()
            try:
                response = client.get("image-to-3d/" + task_id)
                response.raise_for_status()
                result = response.json()
                failures = 0
            except (httpx.HTTPError, ValueError):
                failures += 1
                if failures >= 3:
                    raise RemotePending("云端查询暂时失败，已保留任务 ID，可恢复查询而不重新付费生成")
                time.sleep(5)
                continue
            state = result.get("status")
            if state == "SUCCEEDED":
                url = result.get("model_urls", {}).get("glb")
                if not url:
                    raise ValueError("云端任务完成但没有返回 GLB")
                store.event(job_id, "download", "云端生成完成，正在下载并检查 GLB")
                download_model(url, destination)
                return
            if state in ("FAILED", "CANCELED", "CANCELLED"):
                raise ValueError("云端任务未成功，请到供应商后台查看原因与费用状态")
            progress = result.get("progress")
            store.update(
                job_id,
                lambda item: item.update(provider_progress=progress if isinstance(progress, (int, float)) else None),
            )
            time.sleep(5)
        raise RemotePending("云端任务仍未结束，已暂停本地等待；可恢复查询，不会创建新任务")
