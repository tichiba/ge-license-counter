import google.auth
import google.auth.transport.requests
import requests
import sys
import subprocess
import argparse


def get_quota_project():
    """
    現在アクティブなgcloudプロジェクトを取得します。
    API呼び出し時の利用制限（Quota）管理に使用されます。
    """
    try:
        result = subprocess.run(
            ['gcloud', 'config', 'get-value', 'project'],
            capture_output=True, text=True, check=True
        )
        project = result.stdout.strip()
        if project:
            return project
    except Exception:
        pass
    return None

def get_credentials():
    """
    Google Cloudの認証情報を取得します。
    """
    credentials, _ = google.auth.default(
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials

def list_billing_accounts(token):
    """
    ユーザーがアクセス可能なすべての請求先アカウントを取得します。
    """
    url = "https://cloudbilling.googleapis.com/v1/billingAccounts"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return []
    return response.json().get('billingAccounts', [])

def list_projects(token, billing_account_id):
    """
    指定された請求先アカウントに紐づく、アクティブかつアクセス権限のあるプロジェクトを取得します。
    """
    # 1. 請求先アカウントに紐づくプロジェクトID一覧を取得
    url = f"https://cloudbilling.googleapis.com/v1/billingAccounts/{billing_account_id}/projects"
    headers = {"Authorization": f"Bearer {token}"}
    billing_projects = []
    page_token = None
    while True:
        params = {"pageToken": page_token} if page_token else {}
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            break
        data = response.json()
        billing_projects.extend(data.get('projectBillingInfo', []))
        page_token = data.get('nextPageToken')
        if not page_token:
            break
            
    project_ids = [p['projectId'] for p in billing_projects if p.get('billingEnabled', False)]
    
    # 2. 各プロジェクトの詳細（projectNumberなど）を Cloud Resource Manager API から取得
    projects = []
    for pid in project_ids:
        proj_url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{pid}"
        response = requests.get(proj_url, headers=headers)
        if response.status_code == 200:
            proj_data = response.json()
            if proj_data.get('lifecycleState') == 'ACTIVE':
                projects.append(proj_data)
                
    return projects

def format_date(date_obj):
    """
    APIから返される日付オブジェクトを YYYY-MM-DD 形式に変換します。
    """
    if not date_obj:
        return "N/A"
    return f"{date_obj.get('year')}-{date_obj.get('month'):02d}-{date_obj.get('day'):02d}"

def get_billing_license_configs(token, billing_account_id, quota_project):
    """
    請求先アカウント側から、各プロジェクトへのライセンス分配状況を取得します。
    """
    url = f"https://discoveryengine.googleapis.com/v1alpha/billingAccounts/{billing_account_id}/billingAccountLicenseConfigs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": quota_project
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('billingAccountLicenseConfigs', [])
    return None

def get_project_direct_licenses(token, project_id, quota_project):
    """
    プロジェクト側から、直接紐付いているライセンス情報を取得します。
    """
    url = f"https://discoveryengine.googleapis.com/v1alpha/projects/{project_id}/locations/global/licenseConfigs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": quota_project
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('licenseConfigs', [])
    return []

def main():
    # 実行環境のQuotaプロジェクトを取得
    quota_project = get_quota_project()
    if not quota_project:
        print("Error: Quotaプロジェクトを特定できませんでした。'gcloud config set project' でプロジェクトを設定してください。")
        sys.exit(1)
        
    # 認証トークンの取得
    credentials = get_credentials()
    token = credentials.token
    print(f"Using Quota Project: {quota_project}")
    
    # 引数解析: 第一位置引数として billing_account_id を受け取る
    parser = argparse.ArgumentParser(description="Google Cloud Discovery Engine licenses counter")
    parser.add_argument("billing_account_id", nargs="?", help="Target Billing Account ID (e.g. 012345-6789AB-CDEF01)")
    args = parser.parse_args()

    selected_ba_id = args.billing_account_id
    selected_ba_name = "N/A"

    if not selected_ba_id:
        print("請求先アカウントのリストを取得しています...")
        billing_accounts = list_billing_accounts(token)
        if not billing_accounts:
            print("アクセス可能な請求先アカウントが見つかりませんでした。")
            sys.exit(1)
        
        print("\n利用可能な請求先アカウント一覧:")
        for idx, ba in enumerate(billing_accounts):
            ba_id = ba['name'].split('/')[-1]
            print(f"[{idx}] {ba['displayName']} ({ba_id})")
        
        while True:
            try:
                choice = input("\nスキャン対象の請求先アカウント番号を入力してください: ")
                choice_idx = int(choice)
                if 0 <= choice_idx < len(billing_accounts):
                    selected_ba = billing_accounts[choice_idx]
                    selected_ba_id = selected_ba['name'].split('/')[-1]
                    selected_ba_name = selected_ba['displayName']
                    break
                else:
                    print(f"0 から {len(billing_accounts) - 1} の範囲で入力してください。")
            except ValueError:
                print("有効な数値を入力してください。")
    else:
        # 入力された請求アカウントの表示名を探す（あれば表示）
        billing_accounts = list_billing_accounts(token)
        for ba in billing_accounts:
            ba_id = ba['name'].split('/')[-1]
            if ba_id == selected_ba_id:
                selected_ba_name = ba['displayName']
                break

    print(f"\n選択された請求先アカウント: {selected_ba_name} ({selected_ba_id})")
    
    billing_link_map = {}


    # ステップ1: 選択された請求先アカウントの分配情報を収集
    print(f"請求先アカウント {selected_ba_id} の分配情報を収集中...")
    configs = get_billing_license_configs(token, selected_ba_id, quota_project)
    if configs:
        for config in configs:
            ba_config_id = config['name'].split('/')[-1]
            distributions = config.get('licenseConfigDistributions', {})
            for proj_config_path, _ in distributions.items():
                billing_link_map[proj_config_path] = {
                    "ba_name": selected_ba_name if selected_ba_name != "N/A" else selected_ba_id,
                    "ba_config_id": ba_config_id
                }

    # ステップ2: 請求先アカウントに紐づくプロジェクトのみを走査し、ライセンス情報を取得・名寄せ（Reconcile）
    print(f"請求先アカウント {selected_ba_id} に紐づくプロジェクトをスキャン中...")
    all_data = []
    projects = list_projects(token, selected_ba_id)
    for p in projects:
        proj_id = p['projectId']
        proj_num = p['projectNumber']

        
        project_configs = get_project_direct_licenses(token, proj_id, quota_project)
        for config in project_configs:
            # 期限切れのライセンスは表示から除外
            if config.get('state') == 'EXPIRED': continue
            
            full_path = config['name']
            config_id = full_path.split('/')[-1]
            tier = config.get('subscriptionTier', 'UNKNOWN')
            state = config.get('state', 'UNKNOWN')
            count = config.get('licenseCount', '0')
            start = format_date(config.get('startDate'))
            end = format_date(config.get('endDate'))
            
            # 名寄せ: このプロジェクト側の設定が、請求先アカウントの分配設定と紐付いているか確認
            link = billing_link_map.get(full_path)
            if link:
                source = "Distributed"
                billing_account = link['ba_name']
            else:
                source = "Direct"
                billing_account = "N/A"
            
            all_data.append({
                "source": source,
                "billing_account": billing_account,
                "project_id": proj_id,
                "project_number": proj_num,
                "config_id": config_id,
                "tier": tier,
                "state": state,
                "count": count,
                "start": start,
                "end": end
            })

    if not all_data:
        print("\nアクティブなライセンス設定は見つかりませんでした。")
        return

    # プロジェクトIDとTierでソート
    all_data.sort(key=lambda x: (x['project_id'], x['tier']))

    # 結果の表示（表形式）
    # Source(12), Billing(20), ProjectID(30), Num(15), ConfigID(30), Tier(35), State(10), Count(6), Start(12), End(12)
    fmt = "{:<12} | {:<20} | {:<30} | {:<15} | {:<30} | {:<35} | {:<10} | {:<6} | {:<12} | {:<12}"
    header = fmt.format('Source', 'Billing Account', 'Project ID', 'Project Number', 'Config ID', 'Tier', 'State', 'Count', 'Start', 'End')
    sep = "-" * len(header)
    
    print("\n" + sep)
    print(header)
    print(sep)
    for row in all_data:
        print(fmt.format(
            row['source'],
            row['billing_account'][:20],
            row['project_id'][:30],
            row['project_number'],
            row['config_id'][:30],
            row['tier'][:35],
            row['state'],
            row['count'],
            row['start'],
            row['end']
        ))
    print(sep)

if __name__ == "__main__":
    main()
