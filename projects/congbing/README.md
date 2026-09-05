# 永泰葱饼 · 古镇酥香（一分钟宣传片）（congbing）

## 新剧开工清单

按顺序准备资产，每完成一项运行 `python pipeline.py check projects/congbing` 查看缺口：

### 1. 项目配置（project.json）
- [ ] name / title / style_qualifier（一句话风格定位）
- [ ] style.visual（画面风格段落）/ style.retention（风格不变量）
- [ ] engine.instance_type（plus=更快更好 / default）
- [ ] engine.dual_layout（可选：scene_at_166=双角色时 P2 场景/P3 第二角色；缺省 P2 第二角色/P3 场景）
- [ ] voice_audio_default（提示词是否写音色参考行）
- [ ] source_root（可选：本地资源根目录，render 会自动找手工成片 EP{N}段{M}_*.mp4）

### 2. 角色库 characters（每个角色）
- [ ] name / gender / role（提示词中的角色称谓，如"女性角色"）
- [ ] identity（外形设定：年龄/发型/服装/气质/道具）
- [ ] ref_image（三视图/立绘 —— 可用 `pipeline.py asset --character <key>` 自动生成）
- [ ] voice（音色文件 —— RunningHub 声音设计工作流生成；无对白角色设 "voice_optional": true）
- [ ] retention（人物不变量）/ voice_desc（音色描述）

### 3. 场景库 scenes（每个场景）
- [ ] name / desc（空间描述）/ anchor（机位参照要点）/ retention（场景不变量）
- [ ] extra（风格化元素，如仙侠化特效；写实项目留空）
- [ ] ref_image（场景参照图 —— 可用 `pipeline.py asset --scene <key>` 自动生成）

### 4. 分镜 storyboards/
- [ ] 每集一个 epN.json（schema 见 storyboards/README.md）
- [ ] `python pipeline.py check projects/congbing` 全绿

### 5. 生成与成片
- [ ] `python pipeline.py payload projects/congbing --ep 1` 生成 payload 检查
- [ ] `python pipeline.py batch projects/congbing --ep 1` 串行出段视频（自动账单）
- [ ] `python pipeline.py render projects/congbing --ep 1 --title "第1集"` 合成成片
