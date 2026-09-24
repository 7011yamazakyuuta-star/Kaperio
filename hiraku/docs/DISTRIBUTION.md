# 配布と公開

## 方針

アプリ本体はMITライセンスです。著作権者表示はHiraku contributorsとしています。
第三者のコード・画像には元のライセンスが適用され、本体のMITで上書きしません。
名称の商標調査は未実施です。Hashcat/Openwallの公式製品や公認製品とは表示しません。
これはライセンス対応の作業記録であり、法的保証ではありません。

## 配布物

許可リスト `release-files.json` のファイルだけをソースZIPへ格納します。
個人文書、テスト出力、ログ、設定、トークン、辞書、ハッシュ、仮想環境、
Hashcat、John本体とDLL、Office、GPUドライバーは含めません。
`vendor/office2john.py` とLucideは個別の許諾表示を付けて同梱します。

JohnのWindows版はzip2john.exeだけでは実行できない構成があります。
利用者が公式の配布一式を展開し、その中のzip2john.exeを設定してください。
exeだけを抜き出したり、DLLをこのソースZIPへ追加しないでください。

- [Hashcat公式](https://hashcat.net/hashcat/) / [MIT条件](https://github.com/hashcat/hashcat/blob/v7.1.2/docs/license.txt)
- [John公式](https://www.openwall.com/john/) / [ライセンス](https://www.openwall.com/john/doc/LICENSE.shtml)
- [GPLのバイナリ再配布条件](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html#section3)

外部実行ファイルを別途導入する設計は、そのバイナリを今回のZIPで再配布しないためのものです。
GPLが常に無関係になるという意味ではありません。将来John本体や派生コードを同梱する場合は、
対応ソース・ビルド手順・ライセンス全文・各DLLの条件を含めて改めて確認します。

Python依存パッケージはセットアップ時に利用者が取得します。現在のZIPには含めません。
将来EXE化・オフライン同梱する場合、PDFiumなどの間接依存まで表示・条件を棚卸しします。

## 作成・検証

ワークスペース直下で実行します。

```powershell
python hiraku/scripts/release.py build
python hiraku/scripts/release.py verify outputs/releases/Hiraku-0.1.0-alpha.1-source.zip
```

各ファイルのSHA-256をZIP内のRELEASE-MANIFEST.jsonへ記録し、ZIP自体のSHA-256も別ファイルへ出力します。
チェックサムは破損確認用です。デジタル署名や発行元の真正性を保証するものではありません。
ソースや文書を変更した後はテストとZIP作成をやり直してください。
フォルダ丸ごとの圧縮や、現在の開発ワークスペースの丸ごとGit追加はしません。

## 公開前チェック

1. 許可リストとZIP内容を確認し、個人データ・秘密・実ファイル例がないことを確認する。
2. 新しい展開先で初回セットアップ・起動・既知パスワード解除を確認する。
3. Hashcat、Office、ZIPの検証範囲と未検証OSをリリース説明へ記載する。
4. README、LICENSE、THIRD_PARTY、SECURITYを添付する。
5. 公開するアカウント・リポジトリ名・公開範囲・非公開の脆弱性連絡方法を決める。
6. 管理者が最終確認したZIPまたはそのクリーンな展開内容だけをアップロードする。

公開先は [7011yamazakyuuta-star/hiraku](https://github.com/7011yamazakyuuta-star/hiraku) です。
公開履歴と配布物は [Releases](https://github.com/7011yamazakyuuta-star/hiraku/releases) で確認できます。
ZIP作成コマンド自体はローカル処理だけです。アップロード・新しいリリースの公開は管理者が別途実行します。
