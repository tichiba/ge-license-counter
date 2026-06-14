import google.auth
import google.auth.transport.requests
import requests
import json
import sys
import subprocess

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

def list_projects(token):
    """
    すべてのアクティブなプロジェクトを取得します。
    """
    url = "https://cloudresourcemanager.googleapis.com/v1/projects"
    headers = {"Authorization": f"Bearer {token}"}
    projects = []
    page_token = None
    while True:
        params = {"pageToken": page_token} if page_token else {}
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            break
        data = response.json()
        projects.extend(data.get('projects', []))
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    return [p for p in projects if p['lifecycleState'] == 'ACTIVE']

def get_project_id_from_number(token, project_number, project_map):
    """
    プロジェクト番号をプロジェクトIDに変換します。
    """
    if project_number in project_map:
        return project_map[project_number]
    
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_number}"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        pid = response.json().get('projectId', project_number)
        project_map[project_number] = pid
        return pid
    return project_number

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
    
    project_map = {}
    
    # 請求先側のライセンス設定とプロジェクト側の設定を紐付けるためのマップ
    # Key: プロジェクト側ライセンス設定のフルパス
    # Value: { 請求先名, 請求先側の設定ID }
    billing_link_map = {}

    # ステップ1: 請求先アカウント側の分配情報を収集
    print("請求先アカウントの分配情報を収集中...")
    billing_accounts = list_billing_accounts(token)
    for ba in billing_accounts:
        ba_id = ba['name'].split('/')[-1]
        ba_name = ba['displayName']
        configs = get_billing_license_configs(token, ba_id, quota_project)
        if configs:
            for config in configs:
                ba_config_id = config['name'].split('/')[-1]
                distributions = config.get('licenseConfigDistributions', {})
                for proj_config_path, _ in distributions.items():
                    billing_link_map[proj_config_path] = {
                        "ba_name": ba_name,
                        "ba_config_id": ba_config_id
                    }

    # ステップ2: 全プロジェクトを走査し、ライセンス情報を取得・名寄せ（Reconcile）
    print("各プロジェクトをスキャンしてライセンス情報を名寄せ中...")
    all_data = []
    projects = list_projects(token)
    for p in projects:
        proj_id = p['projectId']
        proj_num = p['projectNumber']
        project_map[proj_num] = proj_id
        
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
