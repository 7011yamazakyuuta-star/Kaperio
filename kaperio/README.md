# Kaperio

個人のファイルを開封し、パスワードなしで保存するローカルアプリです。Hashcatを復元エンジンとして使います。原本を変更せず、作業用コピーと出力を `../outputs/kaperio/` に保存します。

## Windowsで初回セットアップ

Python 3.12以降を [公式サイト](https://www.python.org/downloads/) からインストールします。
公開ZIPを展開し、ルートの `Setup.cmd` を実行します。ネット接続が必要です。
管理者権限は通常不要です。Windowsで検証したPythonは64bit版3.12です。

Hashcat探索には [Hashcat公式](https://hashcat.net/hashcat/) の配布一式を展開し、
起動後の設定画面で `hashcat.exe` を指定します。ZIP探索には
[John公式](https://www.openwall.com/john/) の配布一式の `zip2john.exe` も指定します。
これらのエンジン・DLLはKaperioの公開ZIPには含みません。
既知パスワードの解除・保存だけなら、Hashcat/Johnの導入は不要です。

## 起動

ワークスペース直下の `Kaperio.cmd` をダブルクリックします。ブラウザーが開きます。ファイルを追加し、既知パスワードの入力または探索を選択します。終了は画面右上の電源ボタンです。タブを閉じただけでは処理を継続します。

MITライセンスのソース実行版アルファです。単体EXE、署名付きインストーラー、ストア配布版ではありません。

## 対応範囲

| 入力 | 開封・元形式保存 | Hashcat探索 | 変換 |
|---|---|---|---|
| PDF | 対応 | R2〜R6 / 10400〜10700 | PDF、画像PDF、画像Word、PNG ZIP、既存テキスト |
| Excel .xlsx | 対応 | Office 2007/2010/2013系の認識可能な暗号 | PDF経由の画像化。OfficeまたはLibreOfficeが必要 |
| PowerPoint .pptx | 対応 | 同上 | 同上 |
| Word .docx | 対応 | 同上 | 同上 |
| ZIP | パスワードなしZIPへ再圧縮 | WinZip AES / 認識可能なZipCrypto | 内容一覧とZIP保存 |

Officeのシート保護・編集制限、旧形式の `.xls/.ppt/.doc`、7z、RAR、DRM・証明書方式は現在の対象外です。マクロ有効OOXMLの拡張子は読み込み可能ですが、専用の実ファイル検証は未実施です。すべてのZIP圧縮方式を保証しません。ZIP内でパスワードが混在すると全体の解除に失敗する場合があります。

画像Wordは各ページを画像として配置します。文字を編集できるWordへのOCR変換ではありません。元形式のOffice解除では、復号した文書バイトをそのまま保存します。PDFの署名有効性を維持する機能ではありません。

## 探索

- 文字数は固定文字を含む全体の長さです。先頭・末尾を固定して探索範囲を絞れます。
- 文字数探索は半角の1〜16文字。候補リストはUTF-8、1行1候補です。
- デバイスIDは設定のGPU診断で確認できます。空欄の場合はHashcatの自動選択です。
- 初期値は低負荷、80°C停止、10分上限です。時間上限には初期化時間も含みます。
- PDFの半角マスク探索に限定して最適化カーネル `-O` を使います。候補リストには無条件に適用しません。
- 一時停止はプロセスを停止し、Hashcatの直近のrestoreファイルから再開します。保存後の一部候補を再試行する場合があります。保存地点がまだなければ最初から再試行することを画面に表示します。
- GPU探索は1件ずつ順番に実行します。候補が見つからない場合は範囲内で未発見と表示します。強いパスワードの短時間復元を保証するものではありません。

復元結果は実際に原本を復号し、出力を検証してから成功とします。パスワードは実行中のメモリーに保持します。Hashcatのpotfileは無効です。一時的な結果ファイルは読み取り後に削除します。再開のための候補リスト、ハッシュ、固定文字、元ファイルのコピー、解除済み文書はローカルに残ります。

## OS

| OS | 状態 |
|---|---|
| Windows | このPCで実エンジン・ファイル変換・ブラウザー操作を検証 |
| macOS | 共通Pythonコードと起動スクリプトを用意。実機未検証 |
| Linux | 同上。実機未検証 |
| iOS / Android | PCを処理担当にするWeb/PWA画面。390px幅で検証、実機未検証 |

macOS / LinuxではPython 3.12以降、OSに対応するHashcatとGPUランタイムを準備し、`sh setup.sh`、`sh launch.sh` を実行します。Hashcatの場所は画面で指定するか `KAPERIO_HASHCAT` に設定します。ZIP探索にはそのOS用の `zip2john` をPATHへ配置してください。Office画像化はLibreOfficeを使用します。Windows版の解析バイナリーをほかのOSで実行することはありません。

## スマホから操作

初期設定は `127.0.0.1` 限定です。LANには自動公開しません。スマホ連携用のHTTPSモードを用意しています。これは遠隔操作の基盤で、証明書の導入やスマホ実機確認を含むワンクリック設定は今後の項目です。

端末側で信頼できる証明書を準備した環境で、例として次のように起動できます。

```sh
python app.py --host 192.168.1.20 --tls-cert /path/to/cert.pem --tls-key /path/to/key.pem
```

そのPC自身のプライベートIPv4を指定してください。HTTPのLAN公開やワイルドカード待受は拒否します。接続URLは `outputs/kaperio/launch.json` に保存される起動用URLです。URLに含むトークンは操作権限なので共有相手を限定してください。PCを再起動するとトークンは変わります。外部サービスへの文書アップロードは行いません。ルーターのポート開放や証明書検証無効化は不要な設計にしてください。

ブラウザー画面とPWAはPC上のPython処理へ接続します。iPhoneやAndroid上でHashcat自体を実行するものではありません。iPhoneのMetalネイティブ処理は別途実装・実測が必要です。

## 検証

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\integration.py
```

統合テストは生成したOffice/PDF/ZIPを実際にHashcatで探索します。GPUを使う任意実行テストです。
デバイス1、各探索1分以内を初期値とします。個人ファイルやDownloadsフォルダーは読みません。
ZIP探索テストには別途zip2johnが必要です。通常の単体テストにGPUは不要です。

任意の画面テストはNode.js、Playwright、Edgeの導入後に `node tests/release-smoke.cjs` で実行できます。
生成文書だけを使い、エンジン未導入のクリーンな展開先を対象にします。
既存環境を対象にする場合は第1引数に展開先のkaperioフォルダーを指定してください。

先行ツール調査と改善候補は `docs/research.md`、実測記録は `docs/validation.md` を参照してください。

## 公開・プライバシー

`docs/DISTRIBUTION.md` の許可リスト方式でソースZIPを作成します。
開発フォルダーや `outputs` を丸ごと共有しないでください。
ライセンスは設定画面から閲覧できます。データ保存と制限は `SECURITY.md` を参照してください。
