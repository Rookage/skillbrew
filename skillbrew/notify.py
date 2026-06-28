"""notify：安装完成邮件通知（通用 SMTP（简单邮件传输协议），可选）。

把手工 QQ 邮箱脚本升级成正式特性（用户立规，延续 feedback-install-report-email）：
  - 通用 SMTP，不写死 QQ：预设 qq/163/gmail/outlook + 完全自定义（MAIL_HOST/PORT/USE_SSL）；
  - 凭证走 .env（MAIL_ADDRESS/MAIL_AUTH_CODE/...），.env 已 gitignore，不进仓库（D14）；
  - 可选：没配就不发、不报错；配了才在 install --approve 完成时自动发 HTML 报告；
  - 收件人默认=发件人自己（MAIL_RECEIVER 留空时），方便自通知回执。

凭证读取顺序：真实环境变量 > .env（load_env 默认不覆盖真实 env，D15 可插拔）。
"""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

# 常用服务商预设（服务器/端口/SSL 均为公开信息，非隐私）
_PRESETS: dict[str, dict] = {
    "qq": {"host": "smtp.qq.com", "port": 465, "ssl": True},
    "163": {"host": "smtp.163.com", "port": 465, "ssl": True},
    "gmail": {"host": "smtp.gmail.com", "port": 465, "ssl": True},
    "outlook": {"host": "smtp-mail.outlook.com", "port": 587, "ssl": False},  # 587 走 STARTTLS
}


def _server() -> dict:
    """解析 SMTP 服务器：MAIL_PROVIDER 命中预设 → 用预设；否则读 MAIL_HOST/PORT/USE_SSL 自定义。"""
    name = (os.environ.get("MAIL_PROVIDER") or "").strip().lower()
    if name in _PRESETS:
        return dict(_PRESETS[name])
    host = (os.environ.get("MAIL_HOST") or "").strip()
    port = int(os.environ.get("MAIL_PORT") or "465")
    use_ssl = (os.environ.get("MAIL_USE_SSL") or "1").strip().lower() not in ("0", "false", "no")
    return {"host": host, "port": port, "ssl": use_ssl}


def is_configured() -> bool:
    """是否配齐发件凭证（地址 + 授权码）。配齐才算「要发邮件」。"""
    return bool(os.environ.get("MAIL_ADDRESS") and os.environ.get("MAIL_AUTH_CODE"))


def unconfigured_hint() -> str:
    """未配置时的主动提示（供 CLI 提醒，不报错）。"""
    return (
        "邮件通知未配置（可选）：在 .env 填 MAIL_ADDRESS/MAIL_AUTH_CODE/MAIL_PROVIDER，"
        "install --approve 完成会自动发 HTML 报告；不配就不发、不影响使用。详见 .env.example。"
    )


def send_html(subject: str, html_body: str, *, to: str | None = None) -> dict:
    """发一封 HTML 邮件。未配置返回 skipped（不报错）。

    返回 ``{success: bool, skipped?: bool, error?/reason?: str, to?: str}``。
    """
    if not is_configured():
        return {
            "success": False,
            "skipped": True,
            "reason": "邮件未配置（MAIL_ADDRESS/MAIL_AUTH_CODE）",
        }
    sender = os.environ["MAIL_ADDRESS"]
    auth_code = os.environ["MAIL_AUTH_CODE"]
    srv = _server()
    if not srv["host"]:
        return {"success": False, "skipped": True, "reason": "未配 MAIL_PROVIDER，也未配 MAIL_HOST"}
    to = to or os.environ.get("MAIL_RECEIVER") or sender  # 默认收件人=发件人自己

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if srv["ssl"]:
            with smtplib.SMTP_SSL(
                srv["host"], srv["port"], timeout=30, context=ssl.create_default_context()
            ) as s:
                s.login(sender, auth_code)
                s.sendmail(sender, [to], msg.as_string())
        else:
            with smtplib.SMTP(srv["host"], srv["port"], timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(sender, auth_code)
                s.sendmail(sender, [to], msg.as_string())
        return {"success": True, "to": to}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


def install_report_html(r: dict, src_dir) -> str:
    """从 install 结果生成 HTML 完成报告（确定性、不烧 token）。

    ``r`` 是 install.install() 的返回 dict（含 source_video/items_detail/installed/
    before/after/verified_repo/target_dir/skipped_credentials/skipped_config）。
    """
    from pathlib import Path  # 局部导入，避免模块顶部多一个依赖

    src_dir = Path(src_dir)
    items = r.get("items_detail") or []
    installed = r.get("installed") or []

    def esc(x) -> str:
        return html.escape(str(x)) if x is not None else ""

    rows = []
    for it in items:
        form = it.get("form", "Skill")
        usab = it.get("usability", "ready")
        flag = usab if usab and usab != "ready" else "✓"
        if form == "MCP":
            desc = f"{it.get('transport', 'stdio')} -s {it.get('scope', 'user')} {it.get('command', '')} {' '.join(it.get('args', []))}"
        elif form == "repo":
            desc = f"clone {it.get('repo', '')}@{it.get('branch', 'main')}"
        else:
            desc = it.get("target", "")
        rows.append(
            f"<tr><td style='padding:8px;border:1px solid #e5e7eb;'>{esc(it.get('name', ''))}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;'>{esc(form)}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;'>{esc(desc)}</td>"
            f"<td style='padding:8px;border:1px solid #e5e7eb;'>{esc(flag)}</td></tr>"
        )

    creds = r.get("skipped_credentials") or []
    confs = r.get("skipped_config") or []
    next_items = []
    if creds:
        next_items.append(
            f"配凭证：{', '.join(d['name'] for d in creds)}（见 install_list 的 credential_env）"
        )
    if confs:
        next_items.append(f"改配置：{', '.join(d['name'] for d in confs)}（替换占位符后重跑）")
    if not next_items:
        next_items.append("无待办，可直接使用。")
    next_html = "".join(f"<li>{esc(n)}</li>" for n in next_items)

    form0 = items[0].get("form", "Skill") if items else "Skill"
    repo = r.get("verified_repo") or "(repo 形态取自 items)"

    return f"""\
<html><body style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2329;line-height:1.7;max-width:760px;margin:0 auto;padding:24px;">
<h1 style="font-size:20px;border-left:4px solid #2563eb;padding-left:12px;">skillbrew 安装完成报告</h1>
<p style="color:#6b7280;font-size:13px;">自动通知 · install --approve · 台账真相源 data/registry.db</p>
<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px 16px;margin:18px 0;">
<b>源：</b>{esc(r.get("source_video", ""))}　<b>形态：</b>{esc(form0)}<br>
<b>仓库：</b>{esc(repo)}<br>
<b>安装前 distinct：</b>{esc(r.get("before", "?"))}　<b>安装后 distinct：</b>{esc(r.get("after", "?"))}<br>
<b>目标目录：</b>{esc(r.get("target_dir", ""))}　<b>已落盘：</b>{len(installed)} 个能力
</div>
<h2 style="font-size:16px;color:#2563eb;border-bottom:1px solid #e5e7eb;padding-bottom:6px;">本次安装清单</h2>
<table style="border-collapse:collapse;width:100%;font-size:14px;margin:10px 0;">
<tr style="background:#f3f4f6;"><th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">名称</th><th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">形态</th><th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">说明</th><th style="padding:8px;border:1px solid #e5e7eb;text-align:left;">可用性</th></tr>
{"".join(rows) or "<tr><td colspan=4>无</td></tr>"}
</table>
<h2 style="font-size:16px;color:#2563eb;border-bottom:1px solid #e5e7eb;padding-bottom:6px;">下一步</h2>
<ul style="font-size:14px;">{next_html}</ul>
<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
<p style="font-size:12px;color:#9ca3af;">本邮件由 skillbrew 安装完成流程自动发送（不烧 token，确定性生成）。</p>
</body></html>"""
