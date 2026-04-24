# 🎲 astrbot_plugin_jrrp_only —— 每日运势 & 投喂插件

一个适用于 [AstrBot](https://github.com/Soulter/AstrBot) 的每日运势插件，支持 LLM 生成评论以及通过投喂食物改变运势值。  
**所有界面文本均可完全自定义**，包括“运势”一词、骰子名称、各分数段默认回复等，亦可根据需要切换为“水逆”、“人品”等任意概念。

## ✨ 功能特性

- 🔮 **每日运势**：每天为每位用户生成一个 1~100 的运势值（当日固定）。
- 🧠 **LLM 智能评论**：启用 LLM 时，运势和投喂都会通过设定的人格和提示词生成个性化回复。
- 🎲 **无 LLM 降级**：未开启 LLM 或调用失败时，会使用可配置的默认评论或随机投喂回复。
- 🍎 **投喂互动**：`.feed <食物>` 命令可增减当日运势，LLM 模式下由模型根据人格决定增减量，否则随机增减并给予预制回复。
- ✏️ **完全可定制**：“运势”一词、骰子名称、各分数段默认文案、投喂回复池、人格提示词等均可通过配置文件修改。
- 📂 **数据持久化**：每日数据以 YAML 保存，可配置保留天数，过期自动清理。

## 📦 安装

1. 将本插件文件夹放入 AstrBot 的插件目录（一般为 `plugins/`）。
2. 重启 AstrBot 或在管理面板加载插件。
3. 根据需求修改配置文件（`_conf_schema.json`）中的参数。

## 🕹️ 命令说明

| 命令           | 用法示例         | 说明                                            |
| -------------- | ---------------- | ----------------------------------------------- |
| `/jrrp`        | `/jrrp`          | 获取今天的运势值和评论（LLM/默认）              |
| `/jrrp_new`    | `/jrrp_new`      | 重新生成今日运势（需 `allow_regenerate: true`） |
| `.feed <食物>` | `.feed 草莓蛋糕` | 投喂食物，根据人格判定增减运势值并给出评论      |
| `/jrrp_help`   | `/jrrp_help`     | 显示帮助信息                                    |

### 详细行为解释

**1. `/jrrp`**  
- 首次使用会生成一个随机运势值（范围由 `fortune_range` 控制），当天内多次使用返回相同值。  
- **启用 LLM**：调用装配了 `persona_prompt` 和 `jrrp_prompt_template` 的模型生成评论。  
- **未启用 LLM**：根据运势值所在分段，从 `default_comments` 配置中选取回复（支持 `{dice_name}` 和 `{fortune_name}` 占位符）。

**2. `.feed <食物>`**  
- 必须提供一个食物名称。如果今日运势尚未生成，会自动生成一个初始值。  
- **启用 LLM**：模型根据 `feed_prompt_template`（包含当前运势、食物、人格等）以 JSON 返回增减值 `delta` 和评论 `comment`。JSON 解析失败时自动降级为随机模式。  
- **未启用 LLM**：随机决定增减（增减幅度 1~10），并从 `feed_comments_increase` 或 `feed_comments_decrease` 列表中随机选取一条回复（支持 `{delicacy}` `{delta}` `{fortune_name}` 占位符）。  
- 最终运势值会被限制在 `fortune_range` 范围内，并覆盖保存。

**3. `/jrrp_new`**  
- 仅当 `allow_regenerate` 为 `true` 时可用，会直接重新随机生成运势值并覆盖当日记录，评论逻辑同 `/jrrp`。

## ⚙️ 配置说明

所有配置均可通过修改 `_conf_schema.json` 或在 AstrBot 管理面板中调整。以下为完整的配置项及默认值：

```json
{
  "fortune_name": "运势",                    // 自定义“运势”概念，会替换所有界面上的文字
  "dice_name": "",                          // 骰子名称，留空则自动使用“{fortune_name}骰子”
  "persona_prompt": "你是一个调皮的运势骰子。",
  "fortune_range": {
    "min": 1,
    "max": 100
  },
  "jrrp_prompt_template": "{{persona}}\n...", // /jrrp 的 LLM 提示词模板，使用 {{persona}}、{{fortune_name}}、{{fortune_value}}
  "feed_prompt_template": "{{persona}}\n...", // .feed 的 LLM 提示词模板，使用 {{persona}}、{{fortune_name}}、{{delicacy}}、{{current_fortune}}、{{min_fortune}}、{{max_fortune}}
  "default_comments": {                     // 无 LLM 时各分数段的默认回复
    "high":      "天降祥瑞！今天{fortune_name}爆表，做什么都如有神助！",
    "mid_high":  "{fortune_name}相当不错，适合出门碰碰运气~",
    "mid":       "{fortune_name}平平无奇，是适合摸鱼的一天。",
    "low_mid":   "{fortune_name}略显低迷……建议多喝热水，少说话。",
    "low":       "乌云盖顶！今天的{fortune_name}在谷底，要不苟着别出门了。"
  },
  "feed_comments_increase": [                // 投喂增加运势时的随机回复池（无LLM）
    "美味的{delicacy}！{fortune_name}增加{delta}点！",
    "好吃！你投喂的{delicacy}让我很开心，{fortune_name}+{delta}",
    "谢谢你的{delicacy}，今天运气会更好哦～ +{delta}",
    "唔，{delicacy}真不错，给你添点好运~ +{delta}"
  ],
  "feed_comments_decrease": [                // 投喂减少运势时的随机回复池（无LLM）
    "呃，{delicacy}不太合口味...{fortune_name}减少{delta}点...",
    "呸呸，这{delicacy}好难吃！{fortune_name}减少{delta}点...",
    "你居然给我{delicacy}？心情变差了，{fortune_name}-{delta}",
    "yue...{delicacy}简直可怕，你的{fortune_name}掉了{delta}点。"
  ],
  "data_retention_days": 7,                 // 数据保留天数，0 表示仅保留当天
  "enable_llm_comment": true,               // 是否启用 LLM 生成评论（影响 jrrp 和 feed）
  "allow_regenerate": false,                // 是否允许用户使用 /jrrp_new 重新生成
  "show_fortune_value_first": true          // 是否在回复中优先显示运势数值
}