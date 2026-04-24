"""
astrbot_plugin_jrrp_only - 每日运势插件
当接收到命令 /jrrp 时，根据用户ID和日期管理运势值（1-100随机数），并通过LLM生成基于数值的评论。
数值越高，评论越积极。
当接收到命令 .feed 时，根据投喂的食物增减运势值，结合人格和LLM判定。
运势等词汇可配置。
"""

import asyncio
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
from astrbot.api import logger


class JrrpPlugin(Star):
    """运势插件主类"""

    # 配置键名常量
    CONF_DICE_NAME = "dice_name"
    CONF_FORTUNE_NAME = "fortune_name"
    CONF_FORTUNE_RANGE_MIN = "fortune_range.min"
    CONF_FORTUNE_RANGE_MAX = "fortune_range.max"
    CONF_JRRP_PROMPT_TEMPLATE = "jrrp_prompt_template"
    CONF_FEED_PROMPT_TEMPLATE = "feed_prompt_template"
    CONF_PERSONA_PROMPT = "persona_prompt"
    CONF_DATA_RETENTION_DAYS = "data_retention_days"
    CONF_ENABLE_LLM_COMMENT = "enable_llm_comment"
    CONF_ALLOW_REGENERATE = "allow_regenerate"
    CONF_SHOW_FORTUNE_VALUE_FIRST = "show_fortune_value_first"
    CONF_DEFAULT_COMMENTS = "default_comments"
    CONF_FEED_COMMENTS_INCREASE = "feed_comments_increase"
    CONF_FEED_COMMENTS_DECREASE = "feed_comments_decrease"

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.plugin_name = "astrbot_plugin_jrrp_only"

        # 可配置的运势名称
        self.fortune_name = self.config.get(self.CONF_FORTUNE_NAME, "运势")

        # 骰子名称：若未单独配置，则自动跟随运势名称
        self.dice_name = self.config.get(
            self.CONF_DICE_NAME) or f"{self.fortune_name}骰子"

        # 数值范围
        self.fortune_range_min = self.config.get(
            self.CONF_FORTUNE_RANGE_MIN, 1)
        self.fortune_range_max = self.config.get(
            self.CONF_FORTUNE_RANGE_MAX, 100)

        # 人格提示词
        self.persona_prompt = self.config.get(
            self.CONF_PERSONA_PROMPT, "你是一个调皮的运势骰子。"
        )

        # jrrp 提示词模板
        default_jrrp = (
            "{{persona}}\n"
            "请根据以下运势数值，生成一段简短、有趣、适合今日{{fortune_name}}的评论。"
            f"{self.fortune_name}数值是 {{{{fortune_value}}}}（范围1-100，数值越高代表运势越好）。"
            "请让评论的语气和内容与数值所代表的运气好坏相匹配。"
        )
        self.jrrp_prompt_template = self.config.get(
            self.CONF_JRRP_PROMPT_TEMPLATE, default_jrrp
        )

        # feed 提示词模板
        default_feed = (
            "{{persona}}\n"
            "用户投喂了 {{delicacy}}。当前用户今日{{fortune_name}}为 {{current_fortune}}，"
            "{{fortune_name}}范围是 {{min_fortune}} 到 {{max_fortune}}。\n"
            "请根据你的人格和对该食物的喜好，决定{{fortune_name}}值的增减量"
            "（整数，增减范围通常在1-10之间，根据喜好程度可适当浮动），"
            "并生成一句针对该投喂的回应评论。\n"
            "请以JSON格式返回，包含两个字段：delta（整数，正数表示增加，负数表示减少）"
            "和 comment（字符串，你的回应评论）。只返回JSON，不要有其他内容。"
        )
        self.feed_prompt_template = self.config.get(
            self.CONF_FEED_PROMPT_TEMPLATE, default_feed
        )

        # 默认评论配置（无LLM时使用）
        self.default_comments = self.config.get(self.CONF_DEFAULT_COMMENTS, {})
        # 设置各分数段的默认回退（已改为更泛用的风格）
        self._default_comments_fallback = {
            "high":       "天降祥瑞！今天{fortune_name}爆表，做什么都如有神助！",
            "mid_high":   "{fortune_name}相当不错，适合出门碰碰运气~",
            "mid":        "{fortune_name}平平无奇，是适合摸鱼的一天。",
            "low_mid":    "{fortune_name}略显低迷……建议多喝热水，少说话。",
            "low":        "乌云盖顶！今天的{fortune_name}在谷底，要不苟着别出门了。",
        }

        # 投喂随机回复配置
        self.feed_comments_increase = self.config.get(
            self.CONF_FEED_COMMENTS_INCREASE, []
        )
        self.feed_comments_decrease = self.config.get(
            self.CONF_FEED_COMMENTS_DECREASE, []
        )
        self._feed_comments_increase_fallback = [
            "美味的{delicacy}！{fortune_name}增加{delta}点！",
            "好吃！你投喂的{delicacy}让我很开心，{fortune_name}+{delta}",
            "谢谢你的{delicacy}，今天运气会更好哦～ +{delta}",
            "唔，{delicacy}真不错，给你添点好运~ +{delta}",
        ]
        self._feed_comments_decrease_fallback = [
            "呃，{delicacy}不太合口味...{fortune_name}减少{delta}点...",
            "呸呸，这{delicacy}好难吃！{fortune_name}减少{delta}点...",
            "你居然给我{delicacy}？心情变差了，{fortune_name}-{delta}",
            "yue...{delicacy}简直可怕，你的{fortune_name}掉了{delta}点。",
        ]

        # 其他配置
        self.data_retention_days = self.config.get(
            self.CONF_DATA_RETENTION_DAYS, 7)
        self.enable_llm_comment = self.config.get(
            self.CONF_ENABLE_LLM_COMMENT, True)
        self.allow_regenerate = self.config.get(
            self.CONF_ALLOW_REGENERATE, False)
        self.show_fortune_value_first = self.config.get(
            self.CONF_SHOW_FORTUNE_VALUE_FIRST, True)

        # 数据存储
        self.data_dir = StarTools.get_data_dir(self.plugin_name)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.last_cleanup_date = None

        logger.info(f"{self.fortune_name}插件已加载，数据存储目录: {self.data_dir}")
        logger.info(
            f"{self.fortune_name}范围: {self.fortune_range_min}-{self.fortune_range_max}")
        logger.info(f"LLM评论功能: {'启用' if self.enable_llm_comment else '禁用'}")

        asyncio.create_task(self._cleanup_old_data_async())

    # -------------------- 工具方法 --------------------
    def _get_today_str(self) -> str:
        return datetime.now().strftime("%Y%m%d")

    def _get_user_id(self, event: AstrMessageEvent) -> str:
        return event.get_sender_id()

    def _get_data_filename(self, date_str: str, user_id: str) -> Path:
        return self.data_dir / f"{date_str}_{user_id}.yaml"

    def _generate_fortune_value(self) -> int:
        return random.randint(self.fortune_range_min, self.fortune_range_max)

    def _load_fortune_data(self, filepath: Path) -> Optional[int]:
        try:
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and 'fortune_value' in data:
                        return data['fortune_value']
            return None
        except Exception as e:
            logger.error(f"加载数据失败 {filepath}: {e}")
            return None

    def _save_fortune_data(self, filepath: Path, fortune_value: int):
        try:
            data = {
                'fortune_value': fortune_value,
                'generated_at': datetime.now().isoformat()
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True,
                          default_flow_style=False)
            logger.debug(f"数据已保存: {filepath}")
        except Exception as e:
            logger.error(f"保存数据失败 {filepath}: {e}")

    async def _cleanup_old_data_async(self):
        try:
            today_str = self._get_today_str()
            if self.last_cleanup_date == today_str:
                return
            current_date = datetime.strptime(today_str, "%Y%m%d")
            cutoff_date = current_date - \
                timedelta(days=self.data_retention_days)
            files_cleaned = 0
            for filepath in self.data_dir.glob("*.yaml"):
                try:
                    filename = filepath.stem
                    if '_' in filename:
                        date_part = filename.split('_')[0]
                        file_date = datetime.strptime(date_part, "%Y%m%d")
                        if (self.data_retention_days > 0 and file_date < cutoff_date) or \
                           (self.data_retention_days == 0 and file_date.date() != current_date.date()):
                            filepath.unlink()
                            files_cleaned += 1
                            logger.debug(f"已清理旧数据文件: {filepath.name}")
                except (ValueError, IndexError):
                    continue
            if files_cleaned > 0:
                logger.info(f"清理了 {files_cleaned} 个旧数据文件")
            self.last_cleanup_date = today_str
        except Exception as e:
            logger.error(f"清理旧数据失败: {e}")

    def _get_default_comment(self, fortune_value: int) -> str:
        """获取基于运势值的默认评论，优先使用配置，其次回退到硬编码"""
        if fortune_value >= 90:
            key = "high"
        elif fortune_value >= 70:
            key = "mid_high"
        elif fortune_value >= 50:
            key = "mid"
        elif fortune_value >= 30:
            key = "low_mid"
        else:
            key = "low"

        template = self.default_comments.get(key)
        if not template:
            template = self._default_comments_fallback.get(key, "")
        # 替换占位符
        return template.format(dice_name=self.dice_name, fortune_name=self.fortune_name)

    async def _get_llm_comment(self, event: AstrMessageEvent, fortune_value: int) -> Optional[str]:
        if not self.enable_llm_comment:
            return None
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            if not provider_id:
                logger.warning("未找到可用的LLM提供者，使用默认评论")
                return self._get_default_comment(fortune_value)

            prompt = self.jrrp_prompt_template
            prompt = prompt.replace("{{persona}}", self.persona_prompt)
            prompt = prompt.replace("{{fortune_name}}", self.fortune_name)
            prompt = prompt.replace("{{fortune_value}}", str(fortune_value))

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            if llm_resp and hasattr(llm_resp, 'completion_text'):
                return llm_resp.completion_text.strip()
            else:
                logger.warning("LLM返回结果格式异常，使用默认评论")
                return self._get_default_comment(fortune_value)
        except Exception as e:
            logger.error(f"调用LLM生成评论失败: {e}")
            return self._get_default_comment(fortune_value)

    def _get_feed_random_comment(self, is_increase: bool, delta: int, delicacy: str) -> str:
        """无LLM时根据随机增减生成回复，优先使用配置列表，其次回退硬编码"""
        abs_delta = abs(delta)
        # 选择对应列表
        if is_increase:
            pool = self.feed_comments_increase if self.feed_comments_increase else self._feed_comments_increase_fallback
        else:
            pool = self.feed_comments_decrease if self.feed_comments_decrease else self._feed_comments_decrease_fallback

        if not pool:
            # 空列表保护
            return f"投喂了{delicacy}，{self.fortune_name}变化{delta:+}。"
        template = random.choice(pool)
        return template.format(delicacy=delicacy, delta=abs_delta, fortune_name=self.fortune_name)

    async def _get_llm_feed_result(self, event: AstrMessageEvent, delicacy: str,
                                   current_fortune: int) -> Optional[dict]:
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            if not provider_id:
                logger.warning("未找到可用的LLM提供者，无法生成投喂判定")
                return None

            prompt = self.feed_prompt_template
            prompt = prompt.replace("{{persona}}", self.persona_prompt)
            prompt = prompt.replace("{{fortune_name}}", self.fortune_name)
            prompt = prompt.replace("{{delicacy}}", delicacy)
            prompt = prompt.replace(
                "{{current_fortune}}", str(current_fortune))
            prompt = prompt.replace(
                "{{min_fortune}}", str(self.fortune_range_min))
            prompt = prompt.replace(
                "{{max_fortune}}", str(self.fortune_range_max))

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            if not (llm_resp and hasattr(llm_resp, 'completion_text')):
                logger.warning("LLM返回结果格式异常")
                return None

            text = llm_resp.completion_text.strip()
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
                result = json.loads(json_str)
                if 'delta' in result and 'comment' in result:
                    delta = int(result['delta'])
                    return {'delta': delta, 'comment': result['comment']}
            logger.warning(f"LLM返回的投喂判定无法解析，原始文本: {text}")
            return None
        except Exception as e:
            logger.error(f"调用LLM获取投喂结果失败: {e}")
            return None

    # -------------------- 指令处理 --------------------
    @filter.command("jrrp")
    async def handle_jrrp(self, event: AstrMessageEvent):
        try:
            today_str = self._get_today_str()
            user_id = self._get_user_id(event)
            asyncio.create_task(self._cleanup_old_data_async())

            data_file = self._get_data_filename(today_str, user_id)
            fortune_value = self._load_fortune_data(data_file)

            if fortune_value is None:
                fortune_value = self._generate_fortune_value()
                self._save_fortune_data(data_file, fortune_value)
                logger.info(
                    f"为用户 {user_id} 生成新{self.fortune_name}值: {fortune_value}")
            else:
                logger.info(
                    f"读取用户 {user_id} 的已有{self.fortune_name}值: {fortune_value}")

            reply_parts = []
            if self.show_fortune_value_first:
                reply_parts.append(f"今日{self.fortune_name}：{fortune_value}")

            comment = await self._get_llm_comment(event, fortune_value)
            if comment:
                if self.show_fortune_value_first:
                    reply_parts.append(f"\n{comment}")
                else:
                    reply_parts.append(comment)
            else:
                if not self.enable_llm_comment:
                    reply_parts.append("（LLM评论功能已关闭）")
                elif not self.show_fortune_value_first:
                    reply_parts.append(
                        f"今日{self.fortune_name}：{fortune_value}")

            yield event.plain_result("\n".join(reply_parts))
        except Exception as e:
            logger.error(f"处理/jrrp命令时发生错误: {e}")
            yield event.plain_result(f"抱歉，获取{self.fortune_name}时出现了问题，请稍后再试。")

    @filter.command("jrrp_new")
    async def handle_jrrp_new(self, event: AstrMessageEvent):
        if not self.allow_regenerate:
            yield event.plain_result("重新生成功能未开启。")
            return

        try:
            today_str = self._get_today_str()
            user_id = self._get_user_id(event)
            data_file = self._get_data_filename(today_str, user_id)

            fortune_value = self._generate_fortune_value()
            self._save_fortune_data(data_file, fortune_value)
            logger.info(
                f"为用户 {user_id} 重新生成{self.fortune_name}值: {fortune_value}")

            reply_parts = [f"已重新生成今日{self.fortune_name}：{fortune_value}"]
            comment = await self._get_llm_comment(event, fortune_value)
            if comment:
                reply_parts.append(f"\n{comment}")

            yield event.plain_result("\n".join(reply_parts))
        except Exception as e:
            logger.error(f"处理/jrrp_new命令时发生错误: {e}")
            yield event.plain_result(f"抱歉，重新生成{self.fortune_name}时出现了问题，请稍后再试。")

    @filter.command("feed")
    async def handle_feed(self, event: AstrMessageEvent):
        try:
            message = event.message_str.strip()
            parts = message.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result("请指定要投喂的食物，例如：.feed 苹果")
                return
            delicacy = parts[1].strip()

            today_str = self._get_today_str()
            user_id = self._get_user_id(event)
            data_file = self._get_data_filename(today_str, user_id)

            fortune_value = self._load_fortune_data(data_file)
            new_fortune_generated = False
            if fortune_value is None:
                fortune_value = self._generate_fortune_value()
                self._save_fortune_data(data_file, fortune_value)
                new_fortune_generated = True
                logger.info(
                    f"为用户 {user_id} 自动生成今日{self.fortune_name}: {fortune_value}")

            if self.enable_llm_comment:
                llm_result = await self._get_llm_feed_result(event, delicacy, fortune_value)
                if llm_result:
                    delta = llm_result['delta']
                    comment = llm_result['comment']
                else:
                    logger.warning("LLM投喂判定失败，降级为随机增减")
                    is_increase = random.choice([True, False])
                    delta = random.randint(
                        1, 10) if is_increase else -random.randint(1, 10)
                    comment = self._get_feed_random_comment(
                        is_increase, delta, delicacy)
            else:
                is_increase = random.choice([True, False])
                delta = random.randint(
                    1, 10) if is_increase else -random.randint(1, 10)
                comment = self._get_feed_random_comment(
                    is_increase, delta, delicacy)

            new_fortune = fortune_value + delta
            new_fortune = max(self.fortune_range_min, min(
                new_fortune, self.fortune_range_max))
            self._save_fortune_data(data_file, new_fortune)

            reply_parts = []
            if new_fortune_generated:
                reply_parts.append(
                    f"今日{self.fortune_name}尚未生成，已自动生成：{fortune_value}")
            reply_parts.append(
                f"投喂 {delicacy}，{self.fortune_name}变化 {delta:+}")
            reply_parts.append(f"当前{self.fortune_name}：{new_fortune}")
            reply_parts.append(comment)

            yield event.plain_result("\n".join(reply_parts))
        except Exception as e:
            logger.error(f"处理.feed命令时发生错误: {e}")
            yield event.plain_result("投喂时出现了问题，请稍后再试。")

    @filter.command("jrrp_help")
    async def handle_jrrp_help(self, event: AstrMessageEvent):
        help_text = (
            f"{self.fortune_name}插件使用说明：\n\n"
            "命令：\n"
            f"/jrrp - 获取今日{self.fortune_name}值，并使用LLM生成评论\n"
            f"/jrrp_new - 重新生成今日{self.fortune_name}（需要开启重新生成功能）\n"
            f".feed <食物> - 投喂食物，根据人格和LLM判定增减{self.fortune_name}值\n"
            "/jrrp_help - 显示此帮助信息\n\n"
            "说明：\n"
            f"1. {self.fortune_name}值范围：{self.fortune_range_min}-{self.fortune_range_max}\n"
            f"2. {self.fortune_name}值每日生成一次，同一天内多次查询结果相同\n"
            f"3. LLM评论功能：{'已启用' if self.enable_llm_comment else '已禁用'}\n"
            f"4. 重新生成功能：{'已启用' if self.allow_regenerate else '已禁用'}\n"
            f"5. 投喂功能：可使用 .feed <食物> 与骰子互动，影响当日{self.fortune_name}\n"
        )
        yield event.plain_result(help_text)

    async def terminate(self):
        logger.info(f"{self.fortune_name}插件正在卸载...")
