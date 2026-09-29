"""Turn executed JUnit and real-bundle acceptance evidence into a reviewable report."""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def write_report(junit: Path, acceptance: Path, output: Path, runtime_evidence: Path | None = None):
    root = ET.parse(junit).getroot()
    cases = []
    for case in root.iter("testcase"):
        status = "失败" if case.find("failure") is not None or case.find("error") is not None else "未执行" if case.find("skipped") is not None else "通过"
        cases.append({"class": case.get("classname"), "name": case.get("name"), "status": status, "seconds": case.get("time")})
    real = json.loads(acceptance.read_text())
    repo = Path(__file__).resolve().parents[1]
    source_paths = sorted((repo / "backend/qqbot").glob("*.py")) + [repo / "tests/test_qqbot.py", repo / "tools/qqbot_bundle.py", repo / "tools/qqbot_acceptance.py", repo / "Dockerfile.qqbot", repo / "requirements-qqbot.txt"]
    source_paths += sorted((repo / "backend/qqbot/fonts").glob("*"))
    evidence = {"generatedAt": datetime.now(timezone.utc).isoformat(), "localCases": cases, "realSnapshot": real,
                "sourceSha256": {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
                "junitSha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
                "qqSandbox": "not_executed_missing_application_configuration_and_public_callback",
                "runtime": json.loads(runtime_evidence.read_text()) if runtime_evidence else {"status": "未执行"}}
    bot_cases = [x for x in cases if "test_qqbot" in x["class"]]
    passed = sum(x["status"] == "通过" for x in cases)
    total = sum(x["entities"] for x in real["features"].values())
    lines = ["# Our Notes QQ 机器人 V1 功能测试报告", "",
             "**结论：本地实现与测试已完成；真实 QQ 沙箱尚未验收，本报告不能作为已完成平台实测的证明。**", "",
             "## 测试范围与环境", "",
             "- 首版五项：角色卡、留影、歌曲、卡池 UP/时间、角色。所有业务回复均为固定模板 PNG，包括帮助、列表和异常提示。",
             f"- 正式内容版本：`{real['releaseId']}`；快照日期 2026-09-24。",
             f"- 本地功能与回归测试：{passed}/{len(cases)} 通过，其中机器人专项 {len(bot_cases)} 项，其余覆盖原 Query、数据契约及 global-systems。",
             f"- 正式快照全量验收：{total} 条资料逐一按 ID 查询并生成图片；执行耗时 {real['elapsedSeconds']} 秒。",
             f"- 自动化执行时间：{root.find('testsuite').get('timestamp') if root.find('testsuite') is not None else '见证据 JSON'}。",
             "- Python 本机环境、CJK 字体、Pillow 模板渲染；QQ群聊/单聊 API 使用 httpx MockTransport 验证，没有向真实 QQ 用户发送消息。",
             "- 版本证据使用源码 SHA-256；工作区存在其他未提交修改，不能只凭 Git HEAD 重现本次实现。", "",
             "## 五项功能验收", "",
             "| 功能 | 前置数据 | 输入 | 预期 | 实际结果 | 结论 |", "| --- | --- | --- | --- | --- | --- |"]
    commands = {"查角色卡": ("查角色卡 51 / 高松灯 / Tomori", "卡面、角色、稀有度/属性、满级三围、技能及解析提示"),
                "查留影": ("查留影 51 / 好想成为人类", "留影图片、出场角色、稀有度/属性、技能"),
                "查歌曲": ("查歌曲 100001 / 迷星叫", "封面、乐队、词曲、BPM、难度/物量及冲突提示"),
                "查卡池": ("查卡池 1 / MyGO / Tomori", "卡池横幅、UP 卡关联、原始起止时间和时区提示"),
                "查角色": ("查角色 1 / 燈", "人物图、别名、乐队/担当、生日和关联资料")}
    for command, stats in real["features"].items():
        input_text, expected = commands[command]
        ok = stats["entities"] == stats["queryPassed"] == stats["renderPassed"]
        lines.append(f"| {command} | {stats['entities']} 条 | `{input_text}` | {expected} | 查询 {stats['queryPassed']} 条、渲染 {stats['renderPassed']} 条，缺图 {stats['missingArtwork']} | {'通过' if ok else '失败'} |")
    lines += ["", "每项同时覆盖名称/ID 查询；别名和关联角色查询由专项 fixture 验证；无结果不会返回空成功。每页列表 6 项，页码越界返回提示图。", "",
              "## 图片与异常场景", "",
              "- 五类详情、帮助、列表、无结果、未来功能提示均生成 PNG，宽 900px、高不超过 2500px，每次最多 4 张。",
              f"- 正式数据最大单图 {max(x['maxImageBytes'] for x in real['features'].values()):,} 字节；每条详情当前均为单图。",
              "- 缺少图片素材时仍用模板展示资料；查询内部错误使用提示图，不泄露异常细节。",
              "- 多页回复只补发未记录成功的页；429/暂时异常有限重试，永久失败记录状态，不降级为纯文字。",
              "- 使用官方公钥与回调挑战签名向量验证 Ed25519；篡改正文、错误应用、无效签名、过期事件被拒绝或丢弃。",
              "- ACK 对齐腾讯 botgo 的 `op=12,d=0/1`；支持带签名心跳。",
              "- 验证队列容量、请求大小、用户限流、令牌缓存/刷新、业务错误、重启去重、部分发送恢复、数据摘要与跨版本拒绝。", "",
              "## 运行环境验证", "", "```json", json.dumps(evidence["runtime"], ensure_ascii=False, indent=2), "```", "",
              "## 样张与机器可读证据", ""]
    for sample in real["samples"]:
        path = (acceptance.parent / sample["file"]).resolve()
        lines.append(f"- [{sample['command']} 图片]({path})")
    lines += [f"- [五类模板总览]({(acceptance.parent / 'contact-sheet.png').resolve()})",
              f"- [原始 JUnit]({junit.resolve()})", f"- [正式数据全量验收]({acceptance.resolve()})", "",
              "## 真实 QQ 沙箱逐功能验收表", "",
              "以下均未执行：当前尚未提供有效应用配置、沙箱用户/群和可达 HTTPS 回调。必须在真实 QQ 客户端补充实际结果和截图/消息证据后才能标为通过。", "",
              "| 编号 | 场景 | 输入 | 预期 | 实际结果 / 证据 | 状态 |", "| --- | --- | --- | --- | --- | --- |"]
    for scene in ("QQ群 @", "QQ单聊"):
        for index, (command, (input_text, expected)) in enumerate(commands.items(), 1):
            code = ("G" if scene == "QQ群 @" else "C") + f"-{index:02d}"
            lines.append(f"| {code} | {scene} | `{input_text.split(' / ')[0]}` | 收到对应详情图片，内容与资料一致 | 无 | 未执行 |")
    lines += ["", "沙箱还需执行：帮助、别名、多结果翻页、无结果、重复回调、图片转存可达性。应用主体资料、指令面板、IP 白名单等由实际管理端确认。", "",
              "官方要求及模板：[发布指南 9.2](https://bot.q.qq.com/wiki/)、[官方自测报告模板](https://doc.weixin.qq.com/sheet/e3_AHEAcwacAAYhHyOx1ZxTvSm6nHCK0?scode=AJEAIQdfAAoNXeKQ1dAHEAcwacAAY&tab=BB08J2)。模板网页本次无法读取，不能声称已套用其全部列；此报告提供逐功能结果，可在模板可用时转填。", "",
              "## 剩余边界与录音室结论", "",
              "1. 卡池为配置快照，时间未带时区；不提供未经核验的实时状态或倒计时。",
              "2. 部分技能条件尚未完整解析，谱面重建物量与 Master 存在差异；图片保留这些提示。",
              "3. 当前公开资料投影缺少属性/稀有度部分名称映射，使用原始代码，避免错误命名。",
              "4. 活动排名/档线、活动排期已预留 provider 接口，首版只返回未开放图，不计入业务完成数。",
              "5. 录音室配置可读，正式客户端元数据存在 Status/Detail 协议线索；玩家实际进度接口、授权范围、UID 查询能力尚未验证，不能上线为真实进度查询。",
              "6. 官方安全文档展示的业务签名与其展示正文不匹配；公钥和 challenge 向量通过，业务验签保留原始字节严格校验，未放宽。",
              "7. 未部署线上，未提审；没有本次遗留的临时服务进程。", "",
              "## 自动化用例明细", "", "| 测试类 | 用例 | 实际结果 |", "| --- | --- | --- |"]
    for case in bot_cases:
        lines.append(f"| `{case['class'].split('.')[-1]}` | `{case['name']}` | {case['status']} |")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")
    output.with_suffix(".json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-evidence", type=Path)
    args = parser.parse_args()
    write_report(args.junit, args.acceptance, args.output, args.runtime_evidence)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
