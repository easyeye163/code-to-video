# resources/ — 媒体资源索引（不入库目录）

本目录只存放由脚本生成的**资源清单**，媒体本体（图片/音频/视频）一律不上传 Git，统一存放在 MinIO 对象存储，以 URL 形式被工作流与脚本引用。

## 生成资源清单

```bash
cp scripts/minio_config.example.json scripts/minio_config.json   # 填入你的 MinIO 地址与密钥
pip install -r scripts/requirements.txt
python scripts/minio_sync.py scan <资源根目录>    # 扫描 audio/ images/ videos/，生成本目录下 minio-manifest.json
python scripts/minio_sync.py sync                 # 上传到 MinIO
python scripts/minio_sync.py url <相对路径>        # 查询某资源的访问链接
```

`minio-manifest.json`（含相对路径、类型、大小、对象键、访问链接）为生成物，已加入 .gitignore，不入库。
