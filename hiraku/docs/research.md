# 先行ツール調査と開発方針

調査日: 2026-09-24。公式資料の機能説明を比較したものです。競合製品を同じGPUで実測した比較ではありません。

| ツール | 公式に示される特徴 | Hirakuで重視する点 |
|---|---|---|
| [Hashcat](https://github.com/hashcat/hashcat) | GPU/CPU、多数の暗号方式、候補生成、再開、温度監視 | エンジンとして採用。原本の解析・解除・保存を一画面へ |
| [John the Ripper](https://www.openwall.com/john/) | 多数の文書・アーカイブ、CPU/GPU処理 | Office/ZIPの形式抽出ツールを利用。探索エンジン切替は未実装 |
| [Passware Kit Standard](https://www.passware.com/kit-standard/) | 複数のファイル形式のパスワード復元 | 初心者向けの形式認識・結果確認を参考にする |
| [Elcomsoft APDFPR](https://us.elcomsoft.com/apdfpr.html) | PDF探索、辞書・マスク、特定PDF方式のGPU対応、40bit鍵向け専用手法 | 暗号方式ごとの最適な戦略は拡張余地。現段階でこれらの専用手法は未実装 |
| [PDF24](https://tools.pdf24.org/en/unlock-pdf) | 既知パスワードのPDF解除 | 既知パスワードで即保存する経路を実装 |
| [Hashtopolis](https://github.com/hashtopolis/server) | Hashcatの分散処理・管理 | 個人PC優先。複数PCへの分散は未実装 |

全暗号方式、全ハードウェア、互換性、操作性のすべてでHashcatを上回る「完全上位互換」を裏付ける資料は、この調査では確認できませんでした。製品ごとの得意分野があり、競合機能の欠如までは確認していません。

## Hashcatは進化中

[開発版のPCFGドキュメント](https://github.com/hashcat/hashcat/blob/master/docs/hashcat-pcfg.md)では、確率に基づく候補生成とヒントの利用を説明しています。[変更履歴](https://github.com/hashcat/hashcat/blob/master/docs/changes.txt)にも候補生成の拡張があります。これは手元の7.1.2の機能と区別すべき情報です。現在のアプリは手元の7.1.2で動作するマスク・辞書探索を使い、開発版への自動更新は行いません。

## 改善の測り方

1. 候補を減らす: 先頭・末尾、文字種、長さを反映する。英大小数字6文字は56,800,235,584通り、小文字4文字は456,976通り。ただし仮定が誤れば正解を除外する。
2. 試行速度を上げる: GPU選択、カーネル、負荷、温度、ドライバーを同条件で比較する。すべての形式で同じ設定が最速とは限らない。
3. 成功を検証する: 毎秒の試行回数だけでなく、初期化を含む開封完了時間、GPU温度、消費電力、未発見率を記録する。

Hirakuで実装したのは候補範囲の明示・入力支援、重複候補の除去、限定的な最適化カーネル選択、デバイス/負荷/温度指定、時間制限です。独自GPUカーネルや、競合を上回る速度はまだ実証していません。初回コンパイルとキャッシュ済み実行の時間を混ぜた優位性比較はしません。

次の性能検証では同じGPU・ドライバー・暗号・候補集合を固定し、準備実行後に複数回測り、純粋なHashcat CLIとの差を記録します。候補生成戦略の比較は、正解が評価用データへ事前に漏れない独立セットで行います。

## 追加候補

- 7z / RAR: 形式抽出、パスワード検証、同じ内容の非暗号化出力をセットで実装する。
- OCR: スキャンPDF・文字化けするテキスト層を、検索可能PDFと編集可能なWordへ変換する。
- 再発防止: 任意のOSキーチェーン保存、解除済みコピーの整理、バックアップ。
- スマホ連携: HTTPSの端末ペアリング、接続取消、QR表示、実機での転送と中断操作。
- デスクトップ配布: Windows署名済みパッケージ、macOS署名/公証、Linuxパッケージ。

## iPhone GPUについて

[Hashcat公式](https://github.com/hashcat/hashcat)のOS一覧はLinux、Windows、macOSです。[Metal対応の説明](https://github.com/hashcat/hashcat/blob/master/docs/releases_notes_v7.0.0.md)もmacOSの実行環境を対象にしています。

iPhoneのMetal対応GPUが計算に使えないという意味ではありません。Appleは[バックグラウンドGPU用リソース](https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtaskrequest/resources/gpu)と[長時間タスク](https://developer.apple.com/documentation/backgroundtasks/performing-long-running-tasks-on-ios-and-ipados)を提供していますが、対応端末・権限・ライフサイクルを満たすネイティブ実装が必要です。ピーク性能やゲームのベンチマークからパスワード復元速度を断定することはできません。現段階ではiPhone実機ベンチマークもネイティブ移植も行っていません。
