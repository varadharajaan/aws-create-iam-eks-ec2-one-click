# Databricks notebook source
import boto3
import pandas as pd
import requests
import json
import re
from datetime import datetime, timezone


def get_ec2_service_quotas(region, instance_types):
    """
    Fetch EC2 Spot instance quotas for specific instance families in the given region.
    Returns a dictionary of quotas by instance family.
    """
    service_quotas = boto3.client('service-quotas', region_name=region)

    # Get instance families like "m7g" from instance types like "m7g.medium"
    instance_families = set([itype.split('.')[0] for itype in instance_types])
    quotas_by_family = {}

    try:
        response = service_quotas.list_service_quotas(ServiceCode='ec2')
    except Exception as e:
        return {"error": str(e)}

    for quota in response.get('Quotas', []):
        name = quota['QuotaName'].lower()
        for family in instance_families:
            if family in name and 'spot' in name:
                quotas_by_family[family] = {
                    'QuotaName': quota['QuotaName'],
                    'QuotaValue': quota['Value'],
                    'Unit': quota['Unit']
                }

    return quotas_by_family

def fetch_real_interruption_rates():
    """Scrapes the real-time interruption rates from Spot Advisor embedded JSON."""
    url = "https://aws.amazon.com/ec2/spot/instance-advisor/"
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception("Failed to fetch Spot Advisor page")

    match = re.search(r"window\.spotAdvisorData\s*=\s*(\{.*?\});", response.text, re.DOTALL)
    if not match:
        raise Exception("Could not find embedded spotAdvisorData")

    raw_json = match.group(1)
    data = json.loads(raw_json)
    result = {}

    for itype, details in data.get("instanceTypeData", {}).items():
        try:
            rate = float(details.get("interruptionRate", "10%").replace("%", ""))
            result[itype] = rate
        except:
            continue

    return result

def get_spot_placement_scores(region, instance_types):
    ec2 = boto3.client('ec2', region_name=region)
    response = ec2.get_spot_placement_scores(
        InstanceTypes=instance_types,
        TargetCapacity=5,
        SingleAvailabilityZone=True
    )

    scores = []
    for score in response['SpotPlacementScores']:
        for az in score.get('AvailabilityZoneScores', []):
            scores.append({
                'Region': score['Region'],
                'AZ': az['AvailabilityZone'],
                'Score': az['Score']
            })
    return scores

def get_spot_prices(region, instance_types):
    ec2 = boto3.client('ec2', region_name=region)
    now = datetime.now(timezone.utc).isoformat()

    spot_prices = []
    for itype in instance_types:
        response = ec2.describe_spot_price_history(
            InstanceTypes=[itype],
            ProductDescriptions=["Linux/UNIX"],
            StartTime=now,
            MaxResults=1
        )
        if response['SpotPriceHistory']:
            spot_prices.append({
                'InstanceType': itype,
                'AZ': response['SpotPriceHistory'][0]['AvailabilityZone'],
                'SpotPrice': float(response['SpotPriceHistory'][0]['SpotPrice'])
            })
    return spot_prices

def merge_data(region, instance_types):
    prices = get_spot_prices(region, instance_types)
    scores = get_spot_placement_scores(region, instance_types)
    interrupt_rates = fetch_real_interruption_rates()

    df_prices = pd.DataFrame(prices)
    df_scores = pd.DataFrame(scores)
    df = pd.merge(df_prices, df_scores, how='inner', on='AZ')

    df['InterruptRate'] = df['InstanceType'].map(interrupt_rates).fillna(10.0)
    df = df.sort_values(by=['InterruptRate', 'Score'], ascending=[True, False]).reset_index(drop=True)
    return df

# Example usage
if __name__ == "__main__":
    instance_types = ['m7g.medium', 'r6g.large', 'c6gd.large']
    region = 'us-east-1'

    df_result = merge_data(region, instance_types)
    print("\n=== Sorted EC2 Spot Instance Recommendations ===")
    print(df_result[['InstanceType', 'AZ', 'SpotPrice', 'Score', 'InterruptRate']].to_string(index=False))
