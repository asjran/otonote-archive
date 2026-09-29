"""Command -> presentation data; no network, fonts, or game credentials."""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .content import Content
from .presentation import enrich, tile


COMMANDS = {"查角色卡": "memberCards", "查留影": "supportCards", "查歌曲": "musicTracks",
            "查卡池": "gachaPools", "查角色": "characters"}
FUTURE = {"查活动档线": "rankings", "查活动排名": "rankings", "查活动排期": "events",
          "查录音室进度": "studio-progress"}
PAGE_SIZE = 6


@dataclass
class Section:
    title: str
    lines: list[str]


@dataclass
class Reply:
    kind: str
    title: str
    subtitle: str = ""
    sections: list[Section] = field(default_factory=list)
    image: Path | None = None
    accent: str = "#5364D9"
    notice: str = ""
    layout: str = ""
    visual: dict = field(default_factory=dict)


class FutureProvider(Protocol):
    """Providers must include observed/configured time and availability in replies."""
    def query(self, capability: str, keyword: str) -> Reply: ...


def normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def clean(value: object) -> str:
    return re.sub(r"<[^>]*>", "", str(value or "")).replace("\r", "").strip()


def number(value: object) -> str:
    return "未收录" if value is None else str(value)


class Queries:
    def __init__(self, content: Content, providers: dict[str, FutureProvider] | None = None):
        self.content = content
        self.providers = providers or {}

    def help(self) -> Reply:
        return Reply("使用帮助", "Our Notes 资料查询", "输入指令，查看图片资料卡", [
            Section("五项查询", ["查角色卡 高松灯", "查留影 好想成为人类", "查歌曲 迷星叫",
                               "查卡池 MyGO", "查角色 高松灯"]),
            Section("查询方式", ["支持名称、别名和资料 ID。", "多结果时使用图片内的 ID 查看详情。",
                               "翻页示例：查角色卡 高松灯 第2页", "仅使用国际服正式资料快照。"]),
        ])

    def query(self, message: str) -> Reply:
        if not isinstance(message, str) or len(message) > 200:
            return Reply("输入提示", "指令过长", sections=[Section("请缩短输入", ["一次输入一个名称或资料 ID，最多 200 字。", "发送“帮助”查看查询方式。"])])
        text = re.sub(r"^\s*<@!?[A-Za-z0-9_-]+>\s*", "", message).strip()
        text = text.removeprefix("/").strip()
        if text in ("", "帮助", "菜单", "help", "查询帮助"):
            return self.help()
        match = re.match(r"^(查角色卡|查留影|查歌曲|查卡池|查角色|查活动档线|查活动排名|查活动排期|查录音室进度)(.*)$", text)
        if not match:
            return Reply("输入提示", "暂不支持这个指令", sections=[Section("试试这些查询", list(COMMANDS)), Section("帮助", ["发送“帮助”查看示例。"])])
        command, keyword = match.group(1), match.group(2).strip()
        if command in FUTURE:
            capability = FUTURE[command]
            if capability in self.providers:
                return self.providers[capability].query(capability, keyword)
            reason = ("玩家进度接口尚未验证，配置等级不代表实际进度。" if capability == "studio-progress"
                      else "该功能尚未开放，当前没有可用的实时数据。")
            return Reply("功能预告", "这项查询尚未开放", sections=[Section(command, [reason])])
        page = 1
        page_match = re.search(r"(?:^|\s+)第(\d{1,6})页$", keyword)
        if page_match:
            page = int(page_match.group(1))
            keyword = keyword[:page_match.start()].strip()
        dataset = COMMANDS[command]
        items = self.content.systems[dataset] if dataset == "gachaPools" else self.content.catalog[dataset]
        key = normalize(keyword)
        if keyword and not key:
            items = []
        elif key:
            exact = [x for x in items if key in self.identities(x)]
            items = exact or [x for x in items if any(key in s for s in self.terms(dataset, x))]
        if not items:
            return Reply("查询结果", "没有找到对应资料", command,
                         [Section("换一种查询方式", ["请尝试完整名称、角色别名或资料 ID。", "当前查询仅覆盖国际服正式资料快照。", f"示例：{command} 1"])])
        if len(items) == 1 and page == 1:
            return self.detail(dataset, items[0])
        pages = math.ceil(len(items) / PAGE_SIZE)
        if page < 1 or page > pages:
            return Reply("分页提示", "没有这一页", sections=[Section("可用页码", [f"共 {pages} 页，请输入 1 到 {pages}。", f"{command} {keyword} 第1页"])])
        selected = items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        sections = [Section(clean(x.get("displayName") or x.get("title") or x.get("name")),
                            [f"{command} {x['id']}"]) for x in selected]
        if page < pages:
            sections.append(Section("下一页", [f"{command} {keyword} 第{page + 1}页"]))
        reply = Reply(command.removeprefix("查"), f"找到 {len(items)} 项资料", f"第 {page} / {pages} 页 · 用下方指令查详情", sections)
        reply.layout = "list"
        reply.visual = {"items": [tile(self.content, x, dataset) for x in selected], "command": command,
                        "next": f"{command} {keyword} 第{page + 1}页" if page < pages else ""}
        return reply

    def identities(self, item: dict) -> set[str]:
        return {normalize(str(x)) for x in (item["id"], item.get("masterId", item["id"]))}

    def terms(self, dataset: str, item: dict) -> set[str]:
        values = [item.get(k, "") for k in ("displayName", "title", "name", "subtitle", "description", "shortName")]
        values += item.get("aliases", []) + list(item.get("localizedText", {}).values())
        ids = item.get("featuredCharacterIds", []) + item.get("vocalCharacterIds", [])
        if item.get("characterId"):
            ids = ids + [item["characterId"]]
        if dataset == "gachaPools":
            for card_id in item.get("pickupMemberCardIds", []):
                card = self.content.cards.get(card_id, {})
                values += [card.get("displayName", "")]
                ids += [card.get("characterId", "")]
        for identifier in ids:
            char = self.content.characters.get(identifier, {})
            values += [char.get("displayName", "")] + char.get("aliases", [])
        for identifier in item.get("bandIds", []) + ([item["bandId"]] if item.get("bandId") else []):
            values += [self.content.bands.get(identifier, {}).get("displayName", "")]
        return {normalize(str(x)) for x in values if x}

    def detail(self, dataset: str, item: dict) -> Reply:
        label = next(k.removeprefix("查") for k, v in COMMANDS.items() if v == dataset)
        reply = Reply(label, clean(item.get("displayName") or item.get("title") or item.get("name")),
                      f"ID {item['id']} · 国际服", image=self.content.image(item.get("primaryAssetId") or item.get("jacketAssetId") or item.get("profileAssetId")))
        if dataset in ("memberCards", "supportCards"):
            ids = [item["characterId"]] if dataset == "memberCards" else item.get("featuredCharacterIds", [])
            names = [self.content.characters.get(x, {}).get("displayName", x) for x in ids]
            # No guessed taxonomy: use localized taxonomy if available, otherwise expose the source code.
            attrs = self.content.catalog.get("cardTaxonomy", {}).get("attributes", [])
            attr = next((x.get("names", {}).get("zh-CN") or x.get("label") or x.get("name") for x in attrs if x.get("code") == item.get("attributeCode")), None)
            rarities = self.content.catalog.get("cardTaxonomy", {}).get("rarities", [])
            rarity = next((x.get("label") for x in rarities if x.get("value", x.get("code")) == item.get("rarity")), None)
            reply.sections.append(Section("基础资料", ["角色：" + " / ".join(names), f"稀有度：{rarity or number(item.get('rarity'))} · 属性：{attr or '代码 ' + number(item.get('attributeCode'))}",
                f"满级三围  表演 {number(item.get('performancePowerMax'))} / 技巧 {number(item.get('technicPowerMax'))} / 视觉 {number(item.get('visualPowerMax'))}"]))
            for skill in self.content.card_details.get(item["id"], {}).get("skillSummaries", []):
                lines = [clean(skill.get("summary")) or "技能文本未收录"]
                if skill.get("interpretationStatus") != "identified":
                    lines.append("※ 技能条件尚未完整解析，请以游戏内描述为准。")
                reply.sections.append(Section(f"{clean(skill.get('name'))} · Lv.{skill.get('level', '?')}", lines))
            if not self.content.card_details.get(item["id"], {}).get("skillSummaries"):
                reply.sections.append(Section("技能", ["技能资料暂未收录。 "]))
            if ids:
                char = self.content.characters.get(ids[0], {})
                reply.accent = self.content.bands.get(char.get("bandId"), {}).get("mainColor", reply.accent)
        elif dataset == "characters":
            band = self.content.bands.get(item.get("bandId"), {})
            birth = item.get("birthday") or {}
            reply.accent = band.get("mainColor", reply.accent)
            reply.sections = [Section("人物资料", [f"乐队：{band.get('displayName', '未收录')}", f"担当：{item.get('role') or '未收录'}",
                f"生日：{birth.get('month', '?')} 月 {birth.get('day', '?')} 日", "别名：" + " / ".join(item.get("aliases", []))]),
                Section("关联资料", [f"角色卡 {len(item.get('memberCardIds', []))} 张 · 留影 {len(item.get('featuredSupportCardIds', []))} 张",
                                  f"查角色卡 {item['displayName']}", f"查留影 {item['displayName']}"])]
        elif dataset == "musicTracks":
            bpm = item.get("bpm") or {}
            reply.sections = [Section("歌曲资料", ["乐队：" + " / ".join(item.get("bandLabels", [])), "演唱：" + " / ".join(item.get("vocalistLabels", [])),
                f"BPM：{number(bpm.get('min'))} — {number(bpm.get('max'))}", f"作词：{item.get('lyricist') or '未收录'}",
                f"作曲：{item.get('composer') or '未收录'}", f"编曲：{item.get('arranger') or '未收录'}"])]
            charts = [x for x in self.content.catalog["musicCharts"] if x.get("trackId") == item["id"]]
            lines = []
            for chart in charts:
                line = f"{chart.get('difficulty', '?').upper()}  Lv.{number(chart.get('displayLevel', chart.get('level')))} · 物量 {number(chart.get('fullComboCount'))}"
                if chart.get("fullComboStatus") == "conflict":
                    line += f"（重建值；Master {number(chart.get('masterFullComboCount'))}）"
                lines.append(line)
            reply.sections.append(Section("谱面难度 / 物量", lines or ["谱面资料暂未收录。 "]))
            if any(x.get("fullComboStatus") == "conflict" for x in charts):
                reply.notice = "部分谱面物量与 Master 不一致，已标注，待游戏内核验。"
        elif dataset == "gachaPools":
            reply.image = self.content.banner(item)
            reply.sections = [Section("招募时间", [f"开始：{item.get('startAt') or '未配置'}", f"结束：{item.get('endAt') or '未配置'}", "配置时间，时区未核验；不代表实时开放状态。"])]
            cards = [self.content.cards.get(x) for x in item.get("pickupMemberCardIds", [])]
            reply.sections.append(Section("Pick Up 角色卡", [f"{x['displayName']}\n查角色卡 {x['id']}" if x else "UP 卡资料缺失" for x in cards] or ["本快照没有标记 UP 角色卡。 "]))
            reply.notice = "UP 名单来自卡池奖品配置，不根据同期活动或时间猜测。"
        return enrich(self.content, dataset, item, reply)
