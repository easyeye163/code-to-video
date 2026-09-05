# 分镜目录

每集一个文件：`ep1.json`、`ep2.json`…（`--ep N` 寻址）。

```json
{
  "project": "congbing",
  "episode": 1,
  "title": "本集标题",
  "segments": [
    {
      "seg": 1,
      "p1": "角色key（必填）",
      "p2": "第二角色key（可选，双角色对话段）",
      "scene": "场景key（必填）",
      "voice": "音色角色key（缺省用 p1）",
      "duration": 15,
      "summary": "本段一句话概括",
      "shots": [
        { "time": "0s-7s", "desc": "镜头描述", "dialogue": "台词（可选）" },
        { "time": "7s-15s", "desc": "镜头描述" }
      ],
      "soundscape": "环境声",
      "music": "配乐"
    }
  ]
}
```

分段级覆盖字段（覆盖 project.json 默认）：`p1_identity` `p2_identity` `p1_retention` `p2_retention`
`scene_desc` `scene_anchor` `scene_extra` `scene_retention` `style_retention` `drift_clause` `voice_audio`
