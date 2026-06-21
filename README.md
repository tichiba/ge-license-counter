# Gemini ライセンス一覧取得ツール

このツールは、Google Cloud 組織内の **Gemini Enterprise** および **NotebookLM** のサブスクリプション状況を網羅的に一覧化するための Python スクリプトです。

## 特徴

- **網羅的なスキャン**: 「請求先アカウントからの分配」と「プロジェクト単位での直接購入」の両方のルートをスキャンし、すべてのライセンスを捕捉します。
- **名寄せ (Reconciliation)**: 複数の API 視点から見える同じ契約を自動的に統合し、支払元の請求先アカウント名を補完します。
- **詳細な表示**: 
    - プロジェクト ID / 番号
    - ライセンスの種別 (Tier)
    - 契約状態 (State)
    - ライセンス数 (Count)
    - 有効期間 (Start / End Date)
    - ユニークな管理 ID (Config ID)

## 動作要件

以下がインストールされた環境。Google Cloud コンソールの Cloud Shell であればデフォルトで満たしているのでおすすめです。
- Python 3.x
- Google Cloud SDK (gcloud CLI)
- 必要な権限:
    - `billing.accounts.get` または `billing.accounts.getProjectBillingInfo` (請求先アカウントとプロジェクトの紐付け情報の取得)
    - `discoveryengine.billingAccountLicenseConfigs.list` (請求先レベル)
    - `discoveryengine.licenseConfigs.list` (プロジェクトレベル)
    - `resourcemanager.projects.get` (プロジェクト情報取得)

## セットアップ

### 1. 認証 (Cloud Shell で実施する場合はスキップ可)

事前に Google Cloud への認証を行ってください。

```bash
gcloud auth application-default login
```

また、API 呼び出しの実行枠（Quota）となるプロジェクトを設定してください。

```bash
gcloud config set project [YOUR_PROJECT_ID]
```

### 2. ライブラリのインストール

```bash
pip install -r requirements.txt
```


## 使い方

### 基本実行 (対話式選択)

引数を指定せずに実行すると、アクセス可能な請求先アカウントの一覧が表示され、コンソール上で番号を入力して選択できます。

```bash
python list_billing_licenses.py
```


### 請求先アカウントIDを直接指定して実行

第一引数に請求先アカウントID（例：`012345-6789AB-CDEF01`）を直接指定することで、対話式選択をスキップして即時に対象アカウントに紐づくプロジェクトのみをスキャンできます。

```bash
python list_billing_licenses.py [BILLING_ACCOUNT_ID]
```

例：
```bash
python list_billing_licenses.py 012345-6789AB-CDEF01
```

### 出力項目の説明

| 列名 | 説明 |
| :--- | :--- |
| **Source** | 検出ルート (`Distributed`: 請求先から分配 / `Direct`: プロジェクト直接) |
| **Billing Account** | 支払元の請求先アカウント名 |
| **Project ID** | ライセンスが割り当てられているプロジェクトの ID |
| **Config ID** | サブスクリプションのユニークな管理 ID |
| **Tier** | ライセンスの種類 (Gemini Enterprise Plus, NotebookLM 等) |
| **Start / End** | ライセンスの有効期間 |

