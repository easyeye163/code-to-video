# projects/ — 短剧项目目录

每个子目录是一个独立制作项目，`pipeline.py` 按 **项目目录 = 自包含配置** 的方式消费：

```
projects/example/
├── project.json              # 项目配置：引擎(App ID/实例类型/默认参数)、风格、角色、场景
├── prompt_template_single.txt # 单角色镜头的 6 段式提示词模板（{占位符}由分镜数据填充）
├── prompt_template_dual.txt   # 双角色镜头模板
└── storyboards/
    └── epN.json              # 分集分镜：segments[seg/p1/p2/scene/voice/duration/summary/shots/...]
```

- `characters[].ref_image`、`scenes[].ref_image`、`characters[].voice` 填 **MinIO 对象存储路径**（相对资源根目录），媒体文件本体不入库
- `engine.app_id` 填你在 RunningHub 部署的 ai-app 编号；`workflow/` 目录有对应 API 调用 JSON 案例
- `output/` 为 pipeline 产物目录（payload、taskId 状态、成片），已在 .gitignore 中排除

## 常用命令

```bash
python pipeline.py check   projects/example            # 校验项目配置与分镜
python pipeline.py payload projects/example --ep 1      # 生成整集 payload（不消耗币）
python pipeline.py submit  projects/example --ep 1 --seg 1   # 提交单段（消耗币）
python pipeline.py batch   projects/example --ep 1      # 串行批量：自动排队/下载/断点续跑
```

`example/` 是可直接跑通 `check`/`payload` 的模板骨架，复制一份改名后填入你自己的素材与分镜即可开拍。
