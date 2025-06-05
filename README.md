# aws-create-iam-eks-ec2-one-click

# Interactive EKS Cluster Manager

This tool allows you to interactively create and manage AWS EKS clusters for multiple IAM users and AWS accounts. It features dynamic selection of EC2 instance types, per-user customization, robust logging, and output of cluster access instructions.

## Features

- **Interactive Selection:** Choose AWS accounts, users, and per-user cluster settings.
- **Dynamic Instance Type Selection:** Allowed instance types and the default type are loaded from `ec2-region-ami-mapping.json`. Users can pick instance types for each cluster interactively.
- **EKS Best Practices:** Creates clusters with strong defaults (1 node minimum, disk size 20GB, AL2_x86_64 AMI by default).
- **User Access Automation:** Configures `aws-auth` ConfigMap for IAM user access.
- **Access Verification:** Optionally verifies user access after cluster creation.
- **Command Generation:** Saves `kubectl` and AWS CLI commands for both admin and users.
- **Result Logging:** Outputs results and summaries as JSON and TXT reports.

## Prerequisites

- Python 3.8+
- AWS credentials (for admin and users)
- `boto3` library
- IAM permissions to create EKS clusters, nodegroups, IAM roles, and update ConfigMaps
- The configuration file: `ec2-region-ami-mapping.json` in the working directory

## Setup

1. **Clone this repository:**
   ```sh
   git clone <your-repo-url>
   cd <repo-directory>
   ```

2. **Install dependencies:**
   ```sh
   pip install boto3
   ```

3. **Prepare configuration files:**
   - `ec2-region-ami-mapping.json` — defines allowed instance types, AMIs per region, and other EKS settings.
   - `user_config.json` — your IAM user definitions (see your existing format).
   - `admin_config.json` — AWS admin credentials.

## Usage

```sh
python main.py
```

### Workflow

1. **Welcome screen**: Shows available accounts, users, and instance types (from `ec2-region-ami-mapping.json`).
2. **Account selection**: Choose one or more AWS accounts to manage.
3. **User selection**: Choose all users or specific users per account.
4. **Instance type selection**: For each user or cluster, select an instance type from the allowed types. The default is set in the config file.
5. **Cluster configuration**: Set maximum node count; default is 3 (min 1, max 10).
6. **Confirmation**: Review cluster summary before proceeding.
7. **Cluster creation**: Tool creates clusters and nodegroups, configures user access, and verifies.
8. **Results**: Detailed commands and cluster info saved as JSON and TXT.

### Example `ec2-region-ami-mapping.json`

```json
{
  "region_ami_mapping": {
    "us-east-1": "ami-0953476d60561c955",

    "us-east-2": "ami-06c8f2ec674c67112"
  },
  "allowed_instance_types": [
    "t3.micro",
    "t2.micro",
    "c6a.large"
  ],
  "default_instance_type_index": 2,   // 0-based index, so 2 = c6a.large
  "eks_config": {
    "supported_versions": ["1.27", "1.28", "1.29"],
    "default_version": "1.27"
  }
}
```

## Output

- `eks_clusters_created_<timestamp>.json` — Full cluster creation details
- `eks_clusters_simple_<timestamp>.txt` — Human-readable cluster summary
- `kubectl_commands_<timestamp>.txt` — All generated `kubectl`/CLI commands

## Notes

- The script is interactive and will prompt for selections at each step.
- If `default_instance_type_index` is not provided, the first item in the array is used as default.
- If `ec2-region-ami-mapping.json` is missing, sensible defaults will be used.

# AWS Resource Manager

## Overview

**AWS Resource Manager** is a Python tool that helps you manage, analyze, and audit your AWS EKS clusters and EC2 instances using local state files and live AWS API calls. It provides powerful interactive features for live lookups, cost calculations, and consolidated reporting, supporting multi-account and multi-region environments.

---

## Features

- **Interactive Resource Selection**  
  Browse and select EKS or EC2 state files grouped by date, with user-friendly prompts for each day's files.

- **Live AWS Status Lookup**  
  Instantly check the current live status of EKS clusters or EC2 instances using your AWS root credentials.

- **Live Cost Calculation**  
  Calculate up-to-date costs for EKS clusters and EC2 instances, including control plane, node, and storage costs, based on real AWS resource information.

- **Consolidated Reporting**  
  Generates a single, consolidated status or cost report for each execution, with detailed breakdowns by account and resource.

- **Direct Resource Lookup**  
  Find a resource by name or ID and perform an immediate live lookup.

- **Clear, Readable Output**  
  - Files and timestamps displayed in readable IST format.
  - Global continuous resource numbering across all files for easy selection.
  - Summaries with clear totals and cost breakdowns.

---

## Usage

### 1. **Setup**

- Python 3.7+
- Required packages: `boto3`
- Prepare an AWS accounts config file, e.g. `aws_accounts_config.json` (see below).

### 2. **Run the Tool**

```bash
python ec2_eks_lookup_resource.py
```

Start in interactive mode. You’ll be prompted to select an operation:

- EKS Clusters (metadata + optional live lookup)
- EC2 Instances (metadata + optional live lookup)
- EKS/EC2 Live Cost Calculator (fetches current AWS data)
- Direct live lookup (provide resource ID)
- Exit

You can also provide a resource ID directly:

```bash
python ec2_eks_lookup_resource.py i-0ea27a17f321529f1
python ec2_eks_lookup_resource.py eks-cluster-myteam-useast1
```

Or use a custom config file:

```bash
python ec2_eks_lookup_resource.py --config my_aws_config.json
```

### 3. **File Selection**

- The tool scans for EKS/EC2 state JSON files and groups them by date.
- For each date, you’ll be asked whether to process the files from that day.
- Each file’s timestamp is shown in readable IST format.

### 4. **Resource Selection**

- Resources across all selected files are numbered **continuously** (e.g., 1, 2, 3, ...).
- You can select resources by number, by range (e.g., `1-5`), multiple (e.g., `2,4,7`), or `all`.

### 5. **Reporting**

- Reports (live status and cost) are saved per execution in `livestatus/YYYYMMDD/` or `livecost/YYYYMMDD/` folders.
- Each report contains a full summary, detailed resource information, and breakdowns by account.

---

## AWS Accounts Config

Example (`aws_accounts_config.json`):

```json
{
  "accounts": {
    "account01": {
      "email": "aws-root@example.com",
      "access_key": "AKIA....",
      "secret_key": "..."
    },
    "account02": {
      "email": "aws-root2@example.com",
      "access_key": "...",
      "secret_key": "..."
    }
  }
}
```

---

## Example State File Patterns

- `eks_clusters_created_YYYYMMDD_HHMMSS.json`
- `ec2_instances_report_YYYYMMDD_HHMMSS.json`

---

## Key Improvements Over Standard Tools

- **Accurate EKS Control Plane Cost:** $0.65/hour (not $0.10!)  
- **Actual Node Counts:** Live lookup shows precise node count per cluster.
- **Readable Timestamps:** All times shown in IST, not raw timestamps.
- **User-Friendly File Selection:** See, decide, and process only what you need.
- **No Duplicate Numbering:** Resource selection numbers are unique across all files in a session.

---

## Troubleshooting

- If you see `AttributeError: 'AWSResourceManager' object has no attribute 'ask_resource_type'`, make sure the method is present and correctly indented in your class.
- Make sure your AWS credentials in the config file have sufficient permissions.

---

## License

MIT License

---

## Author

- [varadharajaan](https://github.com/varadharajaan)
