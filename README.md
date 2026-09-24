# Hiraku

自分のファイルのパスワード復元と、解除済みファイルの保存を行うローカルアプリです。
MITライセンスのソース公開用アルファ版です。Hashcat公式製品ではありません。

[GitHub](https://github.com/7011yamazakyuuta-star/hiraku) /
[ダウンロード・リリース](https://github.com/7011yamazakyuuta-star/hiraku/releases)

- Windows: Python 3.12以降を用意し、`Setup.cmd`、`Hiraku.cmd` の順に実行します。
- HashcatとZIP探索用zip2johnは別途公式配布元から用意し、設定画面で指定します。
- パスワードが分かるファイルの解除にはHashcatは不要です。
- 原本は変更しません。解除済み文書は暗号化せずローカル保存します。

[セットアップと対応範囲](hiraku/README.md) / [ライセンス](LICENSE) /
[配布手順](hiraku/docs/DISTRIBUTION.md) / [第三者表示](hiraku/THIRD_PARTY.md) /
[安全性と制限](hiraku/SECURITY.md)

Windowsで検証中です。macOS/Linux/スマホ実機、署名付きインストーラー、
OCR、競合より高速という主張は、このリリースの対象ではありません。
