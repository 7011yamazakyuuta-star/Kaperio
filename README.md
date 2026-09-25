# Kaperio

自分のファイルのパスワード復元と、解除済みファイルの保存を行うローカルアプリです。
MITライセンスのオープンソース・アルファ版です。Hashcat公式製品ではありません。

[GitHub](https://github.com/7011yamazakyuuta-star/Kaperio) /
[ダウンロード・リリース](https://github.com/7011yamazakyuuta-star/Kaperio/releases)

- Windows: 配布ZIPを展開し、フォルダー内の `Kaperio.exe` を起動します。`_internal` も必要です。
- macOS: CPUに合うZIPを展開し `Kaperio.app` を起動します。Apple Silicon版とIntel版は別です。
- Linux: tar.gzを展開し `Kaperio/Kaperio` を実行します。x86-64、glibc 2.35以降が対象です。
- 配布バイナリはPython不要です。画面は既定のブラウザーで開きます。
- ソースから起動する場合はPython 3.12を用意し、Windowsでは `Setup.cmd`、`Kaperio.cmd` の順です。
- HashcatとZIP探索用zip2johnは別途公式配布元から用意し、設定画面で指定します。
- パスワードが分かるファイルの解除にはHashcatは不要です。
- 原本は変更しません。解除済み文書は暗号化せずローカル保存します。
- 探索は辞書、マスク、英字大小・末尾数字の変形、辞書＋末尾探索、先頭探索＋辞書の5種類です。
- [速度検証](kaperio/docs/PERFORMANCE.md): PDF R6の辞書探索で旧設定比2.58倍を観測。本家の最速設定を超えたという意味ではありません。

[セットアップと対応範囲](kaperio/README.md) / [ライセンス](LICENSE) /
[配布手順](kaperio/docs/DISTRIBUTION.md) / [第三者表示](kaperio/THIRD_PARTY.md) /
[安全性と制限](kaperio/SECURITY.md)

ストアは使いません。Windowsのコード署名・macOSのDeveloper ID署名と公証は未実施です。
各OSのビルド・起動テストと、実GPUでの復元性能の確認は区別しています。
詳細は[デスクトップ配布](kaperio/docs/DESKTOP.md)を参照してください。
スマホ単体の復元、OCR、本家Hashcatより高速という保証はありません。
