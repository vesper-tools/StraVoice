# 微软 C++ x64 运行库

`build_release.ps1` 从微软官方下载 `vc_redist.x64.exe`，并校验 Authenticode 微软签名及固定 SHA256。

- 官方入口：https://aka.ms/vc14/vc_redist.x64.exe
- 已核对文件版本：14.51.36247.0
- SHA256：843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C
- 官方部署说明：https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/

安装包完整内置此文件。安装前检查 64 位运行库登记版本；缺失或版本较旧时启动官方安装器并请求管理员授权。失败时停止，3010 返回码提示重启，运行库不随本软件卸载。

官方下载链接会更新；文件变化时构建会拒绝继续，维护者须先验证新版签名和兼容性，再更新固定哈希。运行库安装器属于发布依赖，保留在本目录，不提交二进制到 Git。
