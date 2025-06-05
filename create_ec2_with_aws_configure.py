# Databricks notebook source
#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
import glob
import re
import random
import string
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from logger import setup_logger
from typing import Set

class EC2InstanceManager:
    def __init__(self, ami_mapping_file='ec2-region-ami-mapping.json', userdata_file='userdata.sh'):
        self.ami_mapping_file = ami_mapping_file
        self.userdata_file = userdata_file
        self.logger = setup_logger("ec2_instance_manager", "ec2_creation")
        
        # Find the latest credentials file
        self.credentials_file = self.find_latest_credentials_file()
        
        self.load_configurations()
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Read the user data script from external file
        self.user_data_script = self.load_user_data_script()
        
        # Initialize log file
        self.setup_detailed_logging()

    def generate_random_suffix(self, length=4):
        """Generate random alphanumeric suffix for unique naming"""
        characters = string.ascii_lowercase + string.digits
        return ''.join(random.choice(characters) for _ in range(length))
            
    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            self.log_filename = f"ec2_creation_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ec2_operations')
            self.operation_logger.setLevel(logging.INFO)
            
            # Remove existing handlers to avoid duplicates
            for handler in self.operation_logger.handlers[:]:
                self.operation_logger.removeHandler(handler)
            
            # File handler
            file_handler = logging.FileHandler(self.log_filename, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.operation_logger.addHandler(file_handler)
            self.operation_logger.addHandler(console_handler)
            
            # Log initial information
            self.operation_logger.info("=" * 80)
            self.operation_logger.info("EC2 Instance Creation Session Started")
            self.operation_logger.info("=" * 80)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
            self.operation_logger.info(f"Credentials File: {self.credentials_file}")
            self.operation_logger.info(f"User Data Script: {self.userdata_file}")
            self.operation_logger.info(f"AMI Mapping File: {self.ami_mapping_file}")
            self.operation_logger.info(f"Log File: {self.log_filename}")
            self.operation_logger.info("=" * 80)
            
        except Exception as e:
            print(f"Warning: Could not setup detailed logging: {e}")
            self.operation_logger = None

    def log_operation(self, level, message):
        """Log operation to both console and file"""
        if self.operation_logger:
            if level.upper() == 'INFO':
                self.operation_logger.info(message)
            elif level.upper() == 'WARNING':
                self.operation_logger.warning(message)
            elif level.upper() == 'ERROR':
                self.operation_logger.error(message)
            elif level.upper() == 'DEBUG':
                self.operation_logger.debug(message)
        else:
            print(f"[{level.upper()}] {message}")

    def find_latest_credentials_file(self):
        """Find the latest iam_users_credentials file based on timestamp"""
        try:
            # Look for all files matching the pattern
            pattern = "iam_users_credentials_*.json"
            matching_files = glob.glob(pattern)
            
            if not matching_files:
                self.logger.error(f"No files found matching pattern: {pattern}")
                raise FileNotFoundError(f"No IAM credentials files found matching pattern: {pattern}")
            
            self.logger.info(f"Found {len(matching_files)} credential files:")
            
            # Extract timestamps and sort
            file_timestamps = []
            for file_path in matching_files:
                # Extract timestamp from filename
                # Expected format: iam_users_credentials_YYYYMMDD_HHMMSS.json
                match = re.search(r'iam_users_credentials_(\d{8}_\d{6})\.json', file_path)
                if match:
                    timestamp_str = match.group(1)
                    try:
                        # Parse timestamp to datetime for comparison
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        file_timestamps.append((file_path, timestamp, timestamp_str))
                        self.logger.info(f"  📄 {file_path} (timestamp: {timestamp_str})")
                    except ValueError as e:
                        self.logger.warning(f"  ⚠️  {file_path} has invalid timestamp format: {e}")
                else:
                    self.logger.warning(f"  ⚠️  {file_path} doesn't match expected timestamp pattern")
            
            if not file_timestamps:
                raise ValueError("No valid credential files with proper timestamp format found")
            
            # Sort by timestamp (newest first)
            file_timestamps.sort(key=lambda x: x[1], reverse=True)
            
            # Get the latest file
            latest_file, latest_timestamp, latest_timestamp_str = file_timestamps[0]
            
            self.logger.info(f"🎯 Selected latest file: {latest_file}")
            self.logger.info(f"📅 File timestamp: {latest_timestamp_str}")
            self.logger.info(f"📅 Parsed timestamp: {latest_timestamp}")
            
            # Show what files were skipped
            if len(file_timestamps) > 1:
                self.logger.info("📋 Other files found (older):")
                for file_path, timestamp, timestamp_str in file_timestamps[1:]:
                    self.logger.info(f"  📄 {file_path} (timestamp: {timestamp_str})")
            
            return latest_file
            
        except Exception as e:
            self.logger.error(f"Error finding latest credentials file: {e}")
            raise

    def load_configurations(self):
        """Load IAM credentials and AMI mapping configurations"""
        try:
            # Load IAM credentials from the latest file
            if not os.path.exists(self.credentials_file):
                raise FileNotFoundError(f"Credentials file '{self.credentials_file}' not found")
            
            with open(self.credentials_file, 'r', encoding='utf-8') as f:
                self.credentials_data = json.load(f)
            
            self.logger.info(f"✅ Credentials loaded from: {self.credentials_file}")
            
            # Extract and log metadata from credentials file
            if 'created_date' in self.credentials_data:
                self.logger.info(f"📅 Credentials file created: {self.credentials_data['created_date']} {self.credentials_data.get('created_time', '')}")
            if 'created_by' in self.credentials_data:
                self.logger.info(f"👤 Credentials file created by: {self.credentials_data['created_by']}")
            if 'total_users' in self.credentials_data:
                self.logger.info(f"👥 Total users in file: {self.credentials_data['total_users']}")
            
            # Load AMI mappings
            if not os.path.exists(self.ami_mapping_file):
                raise FileNotFoundError(f"AMI mapping file '{self.ami_mapping_file}' not found")
            
            with open(self.ami_mapping_file, 'r', encoding='utf-8') as f:
                self.ami_config = json.load(f)
            
            self.logger.info(f"✅ AMI mappings loaded from: {self.ami_mapping_file}")
            self.logger.info(f"🌍 Supported regions: {list(self.ami_config['region_ami_mapping'].keys())}")
            
        except FileNotFoundError as e:
            self.logger.error(f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            sys.exit(1)

    def load_user_data_script(self):
        """Load the user data script content from external file with proper encoding handling"""
        try:
            if not os.path.exists(self.userdata_file):
                raise FileNotFoundError(f"User data script file '{self.userdata_file}' not found")
            
            # Try different encodings in order of preference
            encodings_to_try = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
            
            user_data_content = None
            encoding_used = None
            
            for encoding in encodings_to_try:
                try:
                    with open(self.userdata_file, 'r', encoding=encoding) as f:
                        user_data_content = f.read()
                    encoding_used = encoding
                    self.logger.info(f"✅ Successfully read user data script using {encoding} encoding")
                    break
                except UnicodeDecodeError as e:
                    self.logger.debug(f"Failed to read with {encoding} encoding: {e}")
                    continue
                except Exception as e:
                    self.logger.debug(f"Error reading with {encoding} encoding: {e}")
                    continue
            
            if user_data_content is None:
                raise ValueError(f"Could not read {self.userdata_file} with any supported encoding")
            
            self.logger.info(f"📜 User data script loaded from: {self.userdata_file}")
            self.logger.info(f"🔤 Encoding used: {encoding_used}")
            self.logger.debug(f"📏 User data script size: {len(user_data_content)} characters")
            
            # Clean up any problematic characters
            user_data_content = user_data_content.replace('\r\n', '\n')  # Normalize line endings
            user_data_content = user_data_content.replace('\r', '\n')    # Handle old Mac line endings
            
            # Validate that it's a bash script
            lines = user_data_content.strip().split('\n')
            if lines and not lines[0].startswith('#!'):
                self.logger.warning("User data script doesn't start with a shebang (#!)")
                # Add shebang if missing
                user_data_content = '#!/bin/bash\n\n' + user_data_content
                self.logger.info("Added #!/bin/bash shebang to user data script")
            
            # Remove any non-ASCII characters that might cause issues
            user_data_content = ''.join(char for char in user_data_content if ord(char) < 128 or char.isspace())
            
            return user_data_content
            
        except FileNotFoundError as e:
            self.logger.error(f"User data script file error: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading user data script: {e}")
            sys.exit(1)

    def display_accounts_menu(self):
        """Display available accounts and return account selection"""
        if 'accounts' not in self.credentials_data:
            self.logger.error("No accounts found in credentials data")
            return []
        
        accounts = list(self.credentials_data['accounts'].items())
        
        self.log_operation('INFO', f"Displaying {len(accounts)} available accounts for selection")
        
        print(f"\n🏦 Available AWS Accounts ({len(accounts)} total):")
        print("=" * 80)
        
        total_users = 0
        regions_used = set()
        
        for i, (account_name, account_data) in enumerate(accounts, 1):
            user_count = len(account_data.get('users', []))
            total_users += user_count
            account_id = account_data.get('account_id', 'Unknown')
            account_email = account_data.get('account_email', 'Unknown')
            
            # Collect regions used in this account
            account_regions = set()
            for user in account_data.get('users', []):
                region = user.get('region', 'unknown')
                account_regions.add(region)
                regions_used.add(region)
            
            print(f"  {i:2}. {account_name}")
            print(f"      📧 Email: {account_email}")
            print(f"      🆔 Account ID: {account_id}")
            print(f"      👥 Users: {user_count}")
            print(f"      🌍 Regions: {', '.join(sorted(account_regions))}")
            
            # Log account details
            self.log_operation('INFO', f"Account {i}: {account_name} ({account_id}) - {user_count} users in regions: {', '.join(sorted(account_regions))}")
            
            # Show some user details
            if user_count > 0:
                print(f"      👤 Sample users:")
                for j, user in enumerate(account_data.get('users', [])[:3], 1):  # Show first 3 users
                    real_user = user.get('real_user', {})
                    full_name = real_user.get('full_name', user.get('username', 'Unknown'))
                    region = user.get('region', 'unknown')
                    print(f"         {j}. {full_name} ({region})")
                if user_count > 3:
                    print(f"         ... and {user_count - 3} more users")
            print()
        
        print("=" * 80)
        print(f"📊 Summary:")
        print(f"   📈 Total accounts: {len(accounts)}")
        print(f"   👥 Total users: {total_users}")
        print(f"   🌍 All regions: {', '.join(sorted(regions_used))}")
        
        self.log_operation('INFO', f"Account summary: {len(accounts)} accounts, {total_users} total users, regions: {', '.join(sorted(regions_used))}")
        
        print(f"\n📝 Selection Options:")
        print(f"   • Single accounts: 1,3,5")
        print(f"   • Ranges: 1-{len(accounts)} (accounts 1 through {len(accounts)})")
        print(f"   • Mixed: 1-2,4 (accounts 1, 2, and 4)")
        print(f"   • All accounts: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select accounts to process: ").strip()
            
            self.log_operation('INFO', f"User input for account selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all accounts")
                return list(range(1, len(accounts) + 1))
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled account selection")
                return []
            
            try:
                selected_indices = self.parse_account_selection(selection, len(accounts))
                if selected_indices:
                    # Show what was selected
                    selected_accounts = []
                    selected_users = 0
                    selected_regions = set()
                    
                    for idx in selected_indices:
                        account_name, account_data = accounts[idx - 1]
                        user_count = len(account_data.get('users', []))
                        account_id = account_data.get('account_id', 'Unknown')
                        
                        # Get regions for this account
                        account_regions = set()
                        for user in account_data.get('users', []):
                            region = user.get('region', 'unknown')
                            account_regions.add(region)
                            selected_regions.add(region)
                        
                        selected_accounts.append({
                            'name': account_name,
                            'id': account_id,
                            'users': user_count,
                            'regions': account_regions
                        })
                        selected_users += user_count
                    
                    print(f"\n✅ Selected {len(selected_indices)} accounts ({selected_users} total users):")
                    print("-" * 60)
                    for i, account_info in enumerate(selected_accounts, 1):
                        print(f"   {i}. {account_info['name']}")
                        print(f"      🆔 {account_info['id']}")
                        print(f"      👥 {account_info['users']} users")
                        print(f"      🌍 {', '.join(sorted(account_info['regions']))}")
                    
                    print("-" * 60)
                    print(f"📊 Total: {len(selected_indices)} accounts, {selected_users} users, {len(selected_regions)} regions")
                    
                    # Log selection details
                    self.log_operation('INFO', f"Selected accounts: {[acc['name'] for acc in selected_accounts]}")
                    self.log_operation('INFO', f"Selection summary: {len(selected_indices)} accounts, {selected_users} users, {len(selected_regions)} regions")
                    
                    confirm = input(f"\n🚀 Proceed with these {len(selected_indices)} accounts? (y/N): ").lower().strip()
                    self.log_operation('INFO', f"User confirmation for selection: '{confirm}'")
                    
                    if confirm == 'y':
                        return selected_indices
                    else:
                        print("❌ Selection cancelled, please choose again.")
                        self.log_operation('INFO', "User cancelled selection, requesting new input")
                        continue
                else:
                    print("❌ No valid accounts selected. Please try again.")
                    self.log_operation('WARNING', "No valid accounts selected from user input")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                self.log_operation('ERROR', f"Invalid account selection format: {e}")
                continue

    def parse_account_selection(self, selection, max_accounts):
        """Parse account selection string and return list of account indices"""
        selected_indices = set()
        
        # Split by comma and process each part
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start < 1 or end > max_accounts:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_accounts})")
                    
                    if start > end:
                        raise ValueError(f"Invalid range {part}: start must be <= end")
                    
                    selected_indices.update(range(start, end + 1))
                    
                except ValueError as e:
                    if "invalid literal" in str(e):
                        raise ValueError(f"Invalid range format: {part}")
                    else:
                        raise
            else:
                # Handle single number
                try:
                    num = int(part)
                    if num < 1 or num > max_accounts:
                        raise ValueError(f"Account number {num} is out of bounds (1-{max_accounts})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid account number: {part}")
        
        return sorted(list(selected_indices))

    def get_selected_accounts_data(self, selected_indices):
        """Get account data for selected indices"""
        accounts = list(self.credentials_data['accounts'].items())
        selected_accounts = {}
        
        for idx in selected_indices:
            account_name, account_data = accounts[idx - 1]
            selected_accounts[account_name] = account_data
        
        return selected_accounts

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client using specific IAM user credentials"""
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test the connection
            ec2_client.describe_regions(RegionNames=[region])
            self.log_operation('INFO', f"Successfully connected to EC2 in {region} using access key: {access_key[:10]}...")
            return ec2_client
            
        except ClientError as e:
            error_msg = f"Failed to connect to EC2 in {region}: {e}"
            self.log_operation('ERROR', error_msg)
            raise
        except Exception as e:
            error_msg = f"Unexpected error connecting to EC2: {e}"
            self.log_operation('ERROR', error_msg)
            raise

    def get_default_vpc(self, ec2_client, region):
        """Get the default VPC for the region"""
        try:
            vpcs = ec2_client.describe_vpcs(
                Filters=[
                    {'Name': 'is-default', 'Values': ['true']}
                ]
            )
            
            if not vpcs['Vpcs']:
                self.log_operation('ERROR', f"No default VPC found in region {region}")
                return None
            
            vpc_id = vpcs['Vpcs'][0]['VpcId']
            self.log_operation('INFO', f"Found default VPC: {vpc_id} in {region}")
            return vpc_id
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting default VPC in {region}: {e}")
            return None

    def _get_unsupported_azs(self, region: str) -> Set[str]:
        """Load unsupported AZs from ec2-region-ami-mapping.json file"""
        try:
            # Adjust the path to your mapping file
            mapping_file_path = os.path.join(os.path.dirname(__file__), 'ec2-region-ami-mapping.json')
            
            if not os.path.exists(mapping_file_path):
                self.log_operation('WARNING', f"Mapping file not found: {mapping_file_path}")
                return set()
            
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            
            # Get unsupported AZs for the specified region
            unsupported_azs = set()
            
            if 'eks_unsupported_azs' in mapping_data and region in mapping_data['eks_unsupported_azs']:
                unsupported_azs = set(mapping_data['eks_unsupported_azs'][region])
                self.log_operation('DEBUG', f"Loaded {len(unsupported_azs)} unsupported AZs for {region} from mapping file")
            else:
                self.log_operation('DEBUG', f"No unsupported AZs found for region {region} in mapping file")
            
            return unsupported_azs
            
        except Exception as e:
            self.log_operation('WARNING', f"Failed to load unsupported AZs from mapping file: {str(e)}")

    def get_default_subnet(self, ec2_client, vpc_id, region):
        """Get a default public subnet from the VPC, filtering out unsupported AZs"""
        try:
            # Load unsupported AZs for this region
            unsupported_azs = self._get_unsupported_azs(region)
            if unsupported_azs:
                self.log_operation('DEBUG', f"Filtering out unsupported AZs in {region}: {unsupported_azs}")
            
            subnets = ec2_client.describe_subnets(
                Filters=[
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                    {'Name': 'default-for-az', 'Values': ['true']}
                ]
            )
            
            if not subnets['Subnets']:
                self.log_operation('ERROR', f"No default subnets found in VPC {vpc_id}")
                return None
            
            # Filter out subnets in unsupported AZs
            supported_subnets = []
            for subnet in subnets['Subnets']:
                az = subnet['AvailabilityZone']
                if az not in unsupported_azs:
                    supported_subnets.append(subnet)
                else:
                    self.log_operation('DEBUG', f"Skipping default subnet {subnet['SubnetId']} in unsupported AZ: {az}")
            
            if not supported_subnets:
                self.log_operation('ERROR', f"No supported default subnets found in VPC {vpc_id} for region {region}")
                return None
            
            # Get the first available supported subnet
            subnet_id = supported_subnets[0]['SubnetId']
            availability_zone = supported_subnets[0]['AvailabilityZone']
            
            self.log_operation('INFO', f"Selected default subnet: {subnet_id} in supported AZ: {availability_zone}")
            return subnet_id
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting default subnet: {e}")
            return None
            
            with open(mapping_file_path, 'r') as f:
                mapping_data = json.load(f)
            
            if 'eks_config' in mapping_data and 'min_subnets_required' in mapping_data['eks_config']:
                return mapping_data['eks_config']['min_subnets_required']
            
            return 2  # Default fallback
            
        except Exception:
            return 2  # Default fallback

    def create_security_group(self, ec2_client, vpc_id, group_name, region):
        """Create a security group that allows all traffic"""
        try:
            # Check if security group already exists
            try:
                existing_sgs = ec2_client.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': [group_name]},
                        {'Name': 'vpc-id', 'Values': [vpc_id]}
                    ]
                )
                
                if existing_sgs['SecurityGroups']:
                    sg_id = existing_sgs['SecurityGroups'][0]['GroupId']
                    self.log_operation('INFO', f"Using existing security group: {sg_id} for {group_name}")
                    return sg_id
                    
            except ClientError:
                pass
            
            # Create new security group
            response = ec2_client.create_security_group(
                GroupName=group_name,
                Description='Security group allowing all traffic for IAM user instances',
                VpcId=vpc_id
            )
            
            sg_id = response['GroupId']
            self.log_operation('INFO', f"Created new security group: {sg_id} with name: {group_name}")
            
            # Add rules to allow all traffic
            ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        'IpProtocol': '-1',  # All protocols
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'Allow all traffic'}]
                    }
                ]
            )
            
            self.log_operation('INFO', f"Added all-traffic ingress rules to security group: {sg_id}")
            return sg_id
            
        except Exception as e:
            self.log_operation('ERROR', f"Error creating security group {group_name}: {e}")
            raise

    def create_instances_for_selected_accounts(self, selected_accounts, instance_type='t3.micro', capacity_type='spot', wait_for_running=True):
        """Create EC2 instances for users in selected accounts"""
        created_instances = []
        failed_instances = []
        
        self.log_operation('INFO', "🚀 Starting EC2 instance creation process")
        self.log_operation('INFO', f"Instance type: {instance_type}")
        self.log_operation('INFO', f"User data script: {self.userdata_file}")
        self.log_operation('INFO', f"Credentials source: {self.credentials_file}")
        self.log_operation('INFO', f"Wait for running: {wait_for_running}")
        
        # Calculate total users
        total_users = sum(len(account_data.get('users', [])) 
                        for account_data in selected_accounts.values())
        self.log_operation('INFO', f"Total users to process: {total_users}")
        
        user_count = 0
        for account_name, account_data in selected_accounts.items():
            account_id = account_data.get('account_id', 'Unknown')
            account_email = account_data.get('account_email', 'Unknown')
            
            self.log_operation('INFO', f"🏦 Processing account: {account_name} ({account_id})")
            
            if 'users' not in account_data:
                self.log_operation('WARNING', f"No users found in account: {account_name}")
                continue
                
            for user_data in account_data['users']:
                user_count += 1
                username = user_data.get('username', 'unknown')
                region = user_data.get('region', 'us-east-1')
                access_key = user_data.get('access_key_id', '')
                secret_key = user_data.get('secret_access_key', '')
                real_user_info = user_data.get('real_user', {})
                
                real_name = real_user_info.get('full_name', username)
                
                self.log_operation('INFO', f"👤 [{user_count}/{total_users}] Processing user: {username} ({real_name}) in {region}")
                
                if not access_key or not secret_key:
                    error_msg = "Missing AWS credentials"
                    self.log_operation('ERROR', f"❌ {username}: {error_msg}")
                    failed_instances.append({
                        'username': username,
                        'real_name': real_name,
                        'region': region,
                        'account_name': account_name,
                        'account_id': account_id,
                        'error': error_msg
                    })
                    continue
                
                try:
                    # Create EC2 client with user's credentials
                    ec2_client = self.create_ec2_client(access_key, secret_key, region)
                    
                    # Create instance
                    instance_info = self.create_instance(
                        ec2_client, 
                        self.user_data_script, 
                        region, 
                        username,
                        real_user_info,
                        access_key,      # Pass credentials
                        secret_key,      # Pass credentials
                        instance_type,
                        capacity_type
                    )
                    
                    # Wait for instance to be running (optional)
                    if wait_for_running:
                        running_info = self.wait_for_instance_running(
                            ec2_client, 
                            instance_info['instance_id'], 
                            username
                        )
                        if running_info:
                            instance_info.update(running_info)
                    
                    # Add account and user details
                    instance_info.update({
                        'account_name': account_name,
                        'account_id': account_id,
                        'account_email': account_email,
                        'user_data': user_data,
                        'created_at': self.current_time
                    })
                    
                    created_instances.append(instance_info)
                    
                    # Print success message
                    print(f"\n🎉 SUCCESS: Instance created for {real_name}")
                    print(f"   👤 Username: {username}")
                    print(f"   📍 Instance ID: {instance_info['instance_id']}")
                    print(f"   🌍 Region: {region}")
                    print(f"   💻 Instance Type: {instance_info['instance_type']}")
                    print(f"   🏦 Account: {account_name} ({account_id})")
                    if 'public_ip' in instance_info:
                        print(f"   🌐 Public IP: {instance_info['public_ip']}")
                    if 'startup_time_seconds' in instance_info:
                        print(f"   ⏱️  Startup Time: {instance_info['startup_time_seconds']}s")
                    print("-" * 60)
                    
                except Exception as e:
                    error_msg = str(e)
                    self.log_operation('ERROR', f"❌ Failed to create instance for {username}: {error_msg}")
                    failed_instances.append({
                        'username': username,
                        'real_name': real_name,
                        'region': region,
                        'account_name': account_name,
                        'account_id': account_id,
                        'error': error_msg
                    })
                    print(f"\n❌ FAILED: Instance creation failed for {real_name}")
                    print(f"   👤 Username: {username}")
                    print(f"   🏦 Account: {account_name}")
                    print(f"   Error: {error_msg}")
                    print("-" * 60)
                    continue
        
        self.log_operation('INFO', f"Instance creation completed - Created: {len(created_instances)}, Failed: {len(failed_instances)}")
        return created_instances, failed_instances

    def wait_for_instance_running(self, ec2_client, instance_id, username, timeout=300):
        """Wait for instance to be in running state"""
        self.log_operation('INFO', f"⏳ Waiting for instance {instance_id} to reach running state (timeout: {timeout}s)")
        
        start_time = time.time()
        last_state = None
        
        while time.time() - start_time < timeout:
            try:
                response = ec2_client.describe_instances(InstanceIds=[instance_id])
                instance = response['Reservations'][0]['Instances'][0]
                state = instance['State']['Name']
                
                # Log state changes
                if state != last_state:
                    self.log_operation('INFO', f"Instance {instance_id} state changed: {last_state} → {state}")
                    last_state = state
                
                if state == 'running':
                    public_ip = instance.get('PublicIpAddress', 'N/A')
                    private_ip = instance.get('PrivateIpAddress', 'N/A')
                    
                    elapsed_time = int(time.time() - start_time)
                    self.log_operation('INFO', f"✅ Instance {instance_id} is running (took {elapsed_time}s) - Public: {public_ip}, Private: {private_ip}")
                    
                    return {
                        'state': state,
                        'public_ip': public_ip,
                        'private_ip': private_ip,
                        'startup_time_seconds': elapsed_time
                    }
                elif state in ['terminated', 'terminating']:
                    self.log_operation('ERROR', f"❌ Instance {instance_id} terminated unexpectedly")
                    return None
                else:
                    time.sleep(10)
                    
            except Exception as e:
                self.log_operation('ERROR', f"Error checking instance {instance_id} state: {e}")
                time.sleep(10)
        
        elapsed_time = int(time.time() - start_time)
        self.log_operation('ERROR', f"⏰ Timeout waiting for instance {instance_id} after {elapsed_time} seconds")
        return None
    
    def prepare_userdata_with_aws_config(self, base_userdata, access_key, secret_key, region):
        """Add AWS credentials to userdata script"""
        
        # Replace placeholder variables in userdata
        enhanced_userdata = base_userdata.replace('${AWS_ACCESS_KEY_ID}', access_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_SECRET_ACCESS_KEY}', secret_key)
        enhanced_userdata = enhanced_userdata.replace('${AWS_DEFAULT_REGION}', region)
        
        return enhanced_userdata

    def select_capacity_type_ec2(self, user_name: str = None) -> str:
        """Allow user to select EC2 capacity type (Spot or On-Demand)"""
        capacity_options = ['spot', 'on-demand']
        default_type = 'spot'  # Default to spot for cost efficiency
        
        user_prefix = f"for {user_name} " if user_name else ""
        print(f"\n💰 EC2 Capacity Type Selection {user_prefix}")
        print("=" * 60)
        print("Available capacity types:")
        
        for i, capacity_type in enumerate(capacity_options, 1):
            is_default = " (default)" if capacity_type == default_type else ""
            cost_info = " - Up to 90% savings, may be interrupted" if capacity_type == 'spot' else " - Standard pricing, stable"
            print(f"  {i}. {capacity_type.title()}{is_default}{cost_info}")
        
        print("=" * 60)
        
        while True:
            try:
                choice = input(f"Select capacity type (1-{len(capacity_options)}) [default: {default_type}]: ").strip()
                
                if not choice:
                    selected_type = default_type
                    break
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(capacity_options):
                    selected_type = capacity_options[choice_num - 1]
                    break
                else:
                    print(f"❌ Please enter a number between 1 and {len(capacity_options)}")
            except ValueError:
                print("❌ Please enter a valid number")
        
        print(f"✅ Selected capacity type: {selected_type}")
        return selected_type
    
    def create_instance_with_capacity_type(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro', capacity_type='spot'):
        """Create EC2 instance with specified capacity type"""
        self.log_operation('INFO', f"Creating {capacity_type} instance for {username}")
        
        if capacity_type.lower() == 'spot':
            return self.create_instance_spot(ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type, capacity_type)
        else:
            return self.create_instance(ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type, capacity_type)
        
    def create_instance_spot(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro', capacity_type='spot'):
        """Create a Spot EC2 instance for a specific IAM user with enhanced error handling"""
        try:
            # Get AMI for the region
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")
            
            self.log_operation('INFO', f"Starting Spot instance creation for {username} in {region} with AMI: {ami_id}")
            
            # Get default VPC
            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")
            
            # Get default subnet
            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")
            
            random_suffix = self.generate_random_suffix(4)
            
            # Create security group
            sg_name = f"{username}-spot-sg-{random_suffix}"  # Changed to indicate spot
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)
            
            # Prepare tags with real user information
            tags = [
                {'Key': 'Name', 'Value': f'{username}-spot-instance-{random_suffix}'},  # Added 'spot' to name
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Spot-Instance'},  # Updated purpose
                {'Key': 'CapacityType', 'Value': 'spot'},  # Added capacity type tag
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp},
                {'Key': 'InstanceType', 'Value': instance_type}
            ]
            
            # Add real user information to tags
            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})
            
            self.log_operation('INFO', f"Spot instance configuration - Type: {instance_type}, VPC: {vpc_id}, Subnet: {subnet_id}, SG: {sg_id}")
            
            # Enhanced Spot Instance configuration with better error handling
            try:
                # Get current spot price for reference (optional logging)
                try:
                    spot_prices = ec2_client.describe_spot_price_history(
                        InstanceTypes=[instance_type],
                        ProductDescriptions=['Linux/UNIX'],
                        MaxResults=1
                    )
                    if spot_prices['SpotPriceHistory']:
                        current_spot_price = spot_prices['SpotPriceHistory'][0]['SpotPrice']
                        self.log_operation('INFO', f"Current spot price for {instance_type}: ${current_spot_price}/hour")
                except Exception as spot_price_error:
                    self.log_operation('WARNING', f"Could not retrieve spot price: {spot_price_error}")
                
                # Create Spot Instance with enhanced configuration
                response = ec2_client.run_instances(
                    ImageId=ami_id,
                    MinCount=1,
                    MaxCount=1,
                    InstanceType=instance_type,
                    SecurityGroupIds=[sg_id],
                    SubnetId=subnet_id,
                    UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                    InstanceMarketOptions={
                        'MarketType': 'spot',
                        'SpotOptions': {
                            'SpotInstanceType': 'one-time',
                            'InstanceInterruptionBehavior': 'terminate',
                            # Optional: Set max price to prevent unexpected charges
                            # 'MaxPrice': '0.05'  # Uncomment and adjust as needed
                        }
                    },
                    TagSpecifications=[
                        {
                            'ResourceType': 'instance',
                            'Tags': tags
                        },
                        {
                            'ResourceType': 'volume',  # Also tag the EBS volume
                            'Tags': [
                                {'Key': 'Name', 'Value': f'{username}-spot-volume-{random_suffix}'},
                                {'Key': 'Owner', 'Value': username},
                                {'Key': 'CapacityType', 'Value': 'spot'}
                            ]
                        }
                    ],
                    # Enable detailed monitoring for better spot instance management
                    Monitoring={'Enabled': True}
                )
                
                instance_id = response['Instances'][0]['InstanceId']
                instance_type_actual = response['Instances'][0]['InstanceType']
                instance_state = response['Instances'][0]['State']['Name']
                
                # Log spot instance specific information
                if 'SpotInstanceRequestId' in response['Instances'][0]:
                    spot_request_id = response['Instances'][0]['SpotInstanceRequestId']
                    self.log_operation('INFO', f"Spot request ID: {spot_request_id}")
                
                self.log_operation('INFO', f"✅ Successfully created Spot instance {instance_id} for user {username} with suffix {random_suffix}")
                self.log_operation('INFO', f"Instance state: {instance_state}, Actual type: {instance_type_actual}")
                
                # Return enhanced instance information
                return {
                    'instance_id': instance_id,
                    'instance_type': instance_type_actual,
                    'capacity_type': 'spot',  # Explicitly mark as spot
                    'instance_state': instance_state,
                    'region': region,
                    'ami_id': ami_id,
                    'vpc_id': vpc_id,
                    'subnet_id': subnet_id,
                    'security_group_id': sg_id,
                    'username': username,
                    'real_user_info': real_user_info,
                    'userdata_file': self.userdata_file,
                    'credentials_file': self.credentials_file,
                    'random_suffix': random_suffix,
                    'market_type': 'spot'  # For compatibility
                }
                
            except Exception as spot_creation_error:
                # Handle specific spot instance creation errors
                error_msg = str(spot_creation_error)
                
                if 'SpotMaxPriceTooLow' in error_msg:
                    self.log_operation('ERROR', f"Spot price too low for {instance_type} in {region}")
                    raise ValueError(f"Spot capacity not available for {instance_type} in {region} at current price")
                elif 'InsufficientInstanceCapacity' in error_msg:
                    self.log_operation('ERROR', f"Insufficient spot capacity for {instance_type} in {region}")
                    raise ValueError(f"No spot capacity available for {instance_type} in {region}")
                elif 'SpotFleetRequestConfigurationInvalid' in error_msg:
                    self.log_operation('ERROR', f"Invalid spot configuration for {instance_type}")
                    raise ValueError(f"Invalid spot instance configuration for {instance_type}")
                else:
                    self.log_operation('ERROR', f"Spot instance creation failed: {error_msg}")
                    raise
                
        except ValueError as ve:
            # Re-raise ValueError with context
            self.log_operation('ERROR', f"❌ Configuration error for Spot instance {username}: {str(ve)}")
            raise
        except Exception as e:
            error_msg = str(e)
            self.log_operation('ERROR', f"❌ Failed to create Spot instance for user {username}: {error_msg}")
            
            # Provide helpful error context
            if 'InvalidInstanceType' in error_msg:
                raise ValueError(f"Instance type {instance_type} is not available in region {region}")
            elif 'UnauthorizedOperation' in error_msg:
                raise ValueError(f"Insufficient permissions to create spot instances for user {username}")
            else:
                raise

    def create_instance(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro', capacity_type='on-demand'):        
        """Create an On-Demand EC2 instance for a specific IAM user"""
        try:
            # Get AMI for the region
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")
            
            self.log_operation('INFO', f"Starting On-Demand instance creation for {username} in {region} with AMI: {ami_id}")
            
            # Get default VPC
            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")
            
            # Get default subnet
            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")
            
            random_suffix = self.generate_random_suffix(4)
            
            # Create security group
            sg_name = f"{username}-all-traffic-sg-{random_suffix}"
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)
            
            # Prepare tags
            tags = [
                {'Key': 'Name', 'Value': f'{username}-instance-{random_suffix}'},
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Instance'},
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp},
                {'Key': 'InstanceType', 'Value': 'on-demand'}
            ]
            
            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})
            
            self.log_operation('INFO', f"Creating on-demand instance with type {instance_type}, VPC {vpc_id}, Subnet {subnet_id}, SG {sg_id}")
            
            # Create On-Demand Instance (NO Spot options)
            response = ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=instance_type,
                SecurityGroupIds=[sg_id],
                SubnetId=subnet_id,
                UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': tags
                    }
                ]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            instance_type_actual = response['Instances'][0]['InstanceType']
            
            self.log_operation('INFO', f"✅ Successfully created On-Demand instance {instance_id} for user {username} with suffix {random_suffix}")
            
            return {
                'instance_id': instance_id,
                'instance_type': instance_type_actual,
                'region': region,
                'ami_id': ami_id,
                'vpc_id': vpc_id,
                'subnet_id': subnet_id,
                'security_group_id': sg_id,
                'username': username,
                'real_user_info': real_user_info,
                'userdata_file': self.userdata_file,
                'credentials_file': self.credentials_file,
                'market_type': 'on-demand'
            }
        
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to create On-Demand instance for user {username}: {str(e)}")
            raise

    def create_instance_bk(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro'):
        """Try creating a Spot instance; fallback to On-Demand if Spot capacity is unavailable"""
        def run_instance(market_type):
            try:
                instance_market_options = None
                if market_type == 'spot':
                    instance_market_options = {
                        'MarketType': 'spot',
                        'SpotOptions': {
                            'SpotInstanceType': 'one-time',
                            'InstanceInterruptionBehavior': 'terminate'
                        }
                    }

                return ec2_client.run_instances(
                    ImageId=ami_id,
                    MinCount=1,
                    MaxCount=1,
                    InstanceType=instance_type,
                    SecurityGroupIds=[sg_id],
                    SubnetId=subnet_id,
                    UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                    InstanceMarketOptions=instance_market_options,
                    TagSpecifications=[
                        {
                            'ResourceType': 'instance',
                            'Tags': tags
                        }
                    ]
                )
            except Exception as e:
                raise RuntimeError(f"{market_type.capitalize()} instance request failed: {str(e)}")

        try:
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")

            self.log_operation('INFO', f"Starting instance creation for {username} in {region} (attempting Spot instance first)")

            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")

            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")

            random_suffix = self.generate_random_suffix(4)
            sg_name = f"{username}-all-traffic-sg-{random_suffix}"
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)

            tags = [
                {'Key': 'Name', 'Value': f'{username}-instance-{random_suffix}'},
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Instance'},
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp}
            ]

            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})

            self.log_operation('INFO', f"Config - Type: {instance_type}, VPC: {vpc_id}, Subnet: {subnet_id}, SG: {sg_id}")

            # Attempt Spot instance first
            try:
                response = run_instance('spot')
                instance_type_used = 'spot'
            except RuntimeError as spot_error:
                self.log_operation('WARNING', f"⚠️ Spot failed: {str(spot_error)}. Retrying as On-Demand.")
                response = run_instance('ondemand')
                instance_type_used = 'ondemand'

            instance_id = response['Instances'][0]['InstanceId']
            actual_type = response['Instances'][0]['InstanceType']
            self.log_operation('INFO', f"✅ Created {instance_type_used} instance {instance_id} for {username} (suffix: {random_suffix})")

            return {
                'instance_id': instance_id,
                'instance_type': actual_type,
                'instance_market_type': instance_type_used,
                'region': region,
                'ami_id': ami_id,
                'vpc_id': vpc_id,
                'subnet_id': subnet_id,
                'security_group_id': sg_id,
                'username': username,
                'real_user_info': real_user_info,
                'userdata_file': self.userdata_file,
                'credentials_file': self.credentials_file
            }

        except Exception as e:
            self.log_operation('ERROR', f"❌ Instance creation failed for user {username}: {str(e)}")
            raise

    def create_instance_ondemand(self, ec2_client, user_data, region, username, real_user_info, access_key, secret_key, instance_type='t3.micro'):
        """Create an EC2 instance for a specific IAM user"""
        try:
            # Get AMI for the region
            ami_id = self.ami_config['region_ami_mapping'].get(region)
            if not ami_id:
                raise ValueError(f"No AMI mapping found for region: {region}")
            
            self.log_operation('INFO', f"Starting instance creation for {username} in {region} with AMI: {ami_id}")
            
            # Get default VPC
            vpc_id = self.get_default_vpc(ec2_client, region)
            if not vpc_id:
                raise ValueError(f"No default VPC found in region: {region}")
            
            # Get default subnet
            subnet_id = self.get_default_subnet(ec2_client, vpc_id, region)
            if not subnet_id:
                raise ValueError(f"No default subnet found in VPC: {vpc_id}")
            
            random_suffix = self.generate_random_suffix(4)
            
            # Create security group
            sg_name = f"{username}-all-traffic-sg-{random_suffix}"
            sg_id = self.create_security_group(ec2_client, vpc_id, sg_name, region)
            
            # Prepare tags with real user information
            tags = [
                {'Key': 'Name', 'Value': f'{username}-instance-{random_suffix}'},
                {'Key': 'Owner', 'Value': username},
                {'Key': 'Purpose', 'Value': 'IAM-User-Instance'},
                {'Key': 'CreatedBy', 'Value': self.current_user},
                {'Key': 'CreatedAt', 'Value': self.current_time},
                {'Key': 'Region', 'Value': region},
                {'Key': 'UserDataScript', 'Value': self.userdata_file},
                {'Key': 'CredentialsFile', 'Value': self.credentials_file},
                {'Key': 'ExecutionTimestamp', 'Value': self.execution_timestamp}
            ]
            
            # Add real user information to tags
            if real_user_info:
                if real_user_info.get('full_name'):
                    tags.append({'Key': 'RealUserName', 'Value': real_user_info['full_name']})
                if real_user_info.get('email'):
                    tags.append({'Key': 'RealUserEmail', 'Value': real_user_info['email']})
                if real_user_info.get('first_name'):
                    tags.append({'Key': 'RealUserFirstName', 'Value': real_user_info['first_name']})
                if real_user_info.get('last_name'):
                    tags.append({'Key': 'RealUserLastName', 'Value': real_user_info['last_name']})
            
            self.log_operation('INFO', f"Instance configuration - Type: {instance_type}, VPC: {vpc_id}, Subnet: {subnet_id}, SG: {sg_id}")
            
            # Create instance with AWS CLI configuration
            response = ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=instance_type,
                SecurityGroupIds=[sg_id],
                SubnetId=subnet_id,
                UserData=self.prepare_userdata_with_aws_config(user_data, access_key, secret_key, region),
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': tags
                    }
                ]
            )
            
            instance_id = response['Instances'][0]['InstanceId']
            instance_type_actual = response['Instances'][0]['InstanceType']
            
            self.log_operation('INFO', f"✅ Successfully created instance {instance_id} for user {username} with suffix {random_suffix}")            
            
            return {
                'instance_id': instance_id,
                'instance_type': instance_type_actual,
                'region': region,
                'ami_id': ami_id,
                'vpc_id': vpc_id,
                'subnet_id': subnet_id,
                'security_group_id': sg_id,
                'username': username,
                'real_user_info': real_user_info,
                'userdata_file': self.userdata_file,
                'credentials_file': self.credentials_file
            }
            
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to create instance for user {username}: {str(e)}")
            raise

    def save_user_instance_mapping(self, created_instances, failed_instances):
        """Save IAM user to instance ID mapping as JSON file"""
        try:
            mapping_filename = f"iam_user_instance_mapping_{self.execution_timestamp}.json"
            
            # Create mapping data
            mapping_data = {
                "metadata": {
                    "creation_date": self.current_time.split()[0],
                    "creation_time": self.current_time.split()[1],
                    "created_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "credentials_source": self.credentials_file,
                    "userdata_script": self.userdata_file,
                    "total_processed": len(created_instances) + len(failed_instances),
                    "successful_creations": len(created_instances),
                    "failed_creations": len(failed_instances),
                    "success_rate": f"{len(created_instances)/(len(created_instances)+len(failed_instances))*100:.1f}%" if (created_instances or failed_instances) else "0%"
                },
                "successful_mappings": {},
                "failed_mappings": {},
                "detailed_info": {
                    "successful_instances": created_instances,
                    "failed_instances": failed_instances
                }
            }
            
            # Create successful mappings (username -> instance details)
            for instance in created_instances:
                username = instance['username']
                real_user = instance.get('real_user_info', {})
                
                mapping_data["successful_mappings"][username] = {
                    "instance_id": instance['instance_id'],
                    "region": instance['region'],
                    "instance_type": instance['instance_type'],
                    "public_ip": instance.get('public_ip', 'N/A'),
                    "private_ip": instance.get('private_ip', 'N/A'),
                    "account_name": instance['account_name'],
                    "account_id": instance['account_id'],
                    "real_user": {
                        "full_name": real_user.get('full_name', ''),
                        "email": real_user.get('email', ''),
                        "first_name": real_user.get('first_name', ''),
                        "last_name": real_user.get('last_name', '')
                    },
                    "created_at": instance['created_at'],
                    "startup_time_seconds": instance.get('startup_time_seconds', 'N/A'),
                    "aws_console_url": instance.get('user_data', {}).get('console_url', 'N/A'),
                    "tags": {
                        "name": f"{username}-instance",
                        "owner": username,
                        "purpose": "IAM-User-Instance",
                        "created_by": self.current_user
                    }
                }
            
            # Create failed mappings (username -> error details)
            for failure in failed_instances:
                username = failure['username']
                mapping_data["failed_mappings"][username] = {
                    "reason": failure['error'],
                    "region": failure['region'],
                    "account_name": failure['account_name'],
                    "account_id": failure.get('account_id', 'Unknown'),
                    "real_user_name": failure.get('real_name', username),
                    "attempted_at": self.current_time
                }
            
            # Save to file
            with open(mapping_filename, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"✅ IAM user to instance mapping saved to: {mapping_filename}")
            return mapping_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save user-instance mapping: {e}")
            return None

    def save_instance_report(self, created_instances, failed_instances):
        """Save detailed instance creation report to JSON file"""
        try:
            report_filename = f"ec2_instances_report_{self.execution_timestamp}.json"
            
            report_data = {
                "metadata": {
                    "creation_date": self.current_time.split()[0],
                    "creation_time": self.current_time.split()[1],
                    "created_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "credentials_source": self.credentials_file,
                    "userdata_script": self.userdata_file,
                    "ami_mapping_file": self.ami_mapping_file,
                    "log_file": self.log_filename
                },
                "summary": {
                    "total_processed": len(created_instances) + len(failed_instances),
                    "total_created": len(created_instances),
                    "total_failed": len(failed_instances),
                    "success_rate": f"{len(created_instances)/(len(created_instances)+len(failed_instances))*100:.1f}%" if (created_instances or failed_instances) else "0%",
                    "accounts_processed": len(set(instance.get('account_name', '') for instance in created_instances + failed_instances)),
                    "regions_used": list(set(instance.get('region', '') for instance in created_instances + failed_instances))
                },
                "created_instances": created_instances,
                "failed_instances": failed_instances,
                "statistics": {
                    "by_region": {},
                    "by_account": {},
                    "by_instance_type": {},
                    "startup_times": []
                }
            }
            
            # Generate statistics
            for instance in created_instances:
                region = instance.get('region', 'unknown')
                account = instance.get('account_name', 'unknown')
                instance_type = instance.get('instance_type', 'unknown')
                startup_time = instance.get('startup_time_seconds', 0)
                
                # Region statistics
                if region not in report_data["statistics"]["by_region"]:
                    report_data["statistics"]["by_region"][region] = 0
                report_data["statistics"]["by_region"][region] += 1
                
                # Account statistics
                if account not in report_data["statistics"]["by_account"]:
                    report_data["statistics"]["by_account"][account] = 0
                report_data["statistics"]["by_account"][account] += 1
                
                # Instance type statistics
                if instance_type not in report_data["statistics"]["by_instance_type"]:
                    report_data["statistics"]["by_instance_type"][instance_type] = 0
                report_data["statistics"]["by_instance_type"][instance_type] += 1
                
                # Startup times
                if isinstance(startup_time, (int, float)) and startup_time > 0:
                    report_data["statistics"]["startup_times"].append(startup_time)
            
            # Calculate startup time statistics
            startup_times = report_data["statistics"]["startup_times"]
            if startup_times:
                report_data["statistics"]["startup_time_stats"] = {
                    "min": min(startup_times),
                    "max": max(startup_times),
                    "average": sum(startup_times) / len(startup_times),
                    "count": len(startup_times)
                }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"✅ Detailed instance report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save instance report: {e}")
            return None
        
    def convert_selected_users_to_accounts(self, selected_user_indices, user_mapping):
        """Convert selected user indices back to account format for instance creation"""
        if not selected_user_indices or not user_mapping:
            return {}
        
        accounts_data = {}
        
        for user_index in selected_user_indices:
            user_info = user_mapping[user_index]
            account_name = user_info['account_name']
            
            # Initialize account if not exists
            if account_name not in accounts_data:
                accounts_data[account_name] = {
                    'account_id': user_info['account_id'],
                    'account_email': user_info['account_email'],
                    'users': []
                }
            
            # Add user to account
            accounts_data[account_name]['users'].append(user_info['user_data'])
        
        self.log_operation('INFO', f"Converted {len(selected_user_indices)} selected users into {len(accounts_data)} accounts")
        
        # Log conversion details
        for account_name, account_data in accounts_data.items():
            user_count = len(account_data['users'])
            usernames = [u.get('username', 'unknown') for u in account_data['users']]
            self.log_operation('INFO', f"Account {account_name}: {user_count} users - {', '.join(usernames)}")
        
        return accounts_data
    
    def display_users_menu(self, selected_accounts):
        """Display available users and return user selection"""
        # Collect all users from selected accounts
        all_users = []
        for account_name, account_data in selected_accounts.items():
            for user_data in account_data.get('users', []):
                user_info = {
                    'account_name': account_name,
                    'account_id': account_data.get('account_id', 'Unknown'),
                    'account_email': account_data.get('account_email', 'Unknown'),
                    'user_data': user_data,
                    'username': user_data.get('username', 'unknown'),
                    'region': user_data.get('region', 'us-east-1'),
                    'real_user': user_data.get('real_user', {}),
                    'access_key': user_data.get('access_key_id', ''),
                    'secret_key': user_data.get('secret_access_key', '')
                }
                all_users.append(user_info)
        
        if not all_users:
            self.log_operation('ERROR', "No users found in selected accounts")
            return []
        
        self.log_operation('INFO', f"Displaying {len(all_users)} available users for selection")
        
        print(f"\n👥 Available Users ({len(all_users)} total):")
        print("=" * 100)
        
        # Group users by account for better display
        users_by_account = {}
        for user_info in all_users:
            account_name = user_info['account_name']
            if account_name not in users_by_account:
                users_by_account[account_name] = []
            users_by_account[account_name].append(user_info)
        
        user_index = 1
        user_mapping = {}  # Map display index to user info
        
        for account_name, users in users_by_account.items():
            account_id = users[0]['account_id']
            print(f"\n🏦 {account_name} ({account_id}) - {len(users)} users:")
            print("-" * 80)
            
            for user_info in users:
                real_user = user_info['real_user']
                full_name = real_user.get('full_name', user_info['username'])
                email = real_user.get('email', 'N/A')
                region = user_info['region']
                
                print(f"  {user_index:3}. {full_name}")
                print(f"       👤 Username: {user_info['username']}")
                print(f"       📧 Email: {email}")
                print(f"       🌍 Region: {region}")
                print(f"       🔑 Has Credentials: {'✅' if user_info['access_key'] and user_info['secret_key'] else '❌'}")
                
                user_mapping[user_index] = user_info
                user_index += 1
                print()
        
        print("=" * 100)
        print(f"📊 Summary:")
        print(f"   📈 Total accounts: {len(users_by_account)}")
        print(f"   👥 Total users: {len(all_users)}")
        
        # Count users by region
        regions = {}
        for user_info in all_users:
            region = user_info['region']
            regions[region] = regions.get(region, 0) + 1
        print(f"   🌍 Regions: {', '.join(f'{region}({count})' for region, count in sorted(regions.items()))}")
        
        self.log_operation('INFO', f"User summary: {len(all_users)} users across {len(users_by_account)} accounts in {len(regions)} regions")
        
        print(f"\n📝 Selection Options:")
        print(f"   • Single users: 1,3,5")
        print(f"   • Ranges: 1-{len(all_users)} (users 1 through {len(all_users)})")
        print(f"   • Mixed: 1-5,8,10-12 (users 1-5, 8, and 10-12)")
        print(f"   • All users: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select users to process: ").strip()
            
            self.log_operation('INFO', f"User input for user selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all users")
                return list(range(1, len(all_users) + 1)), user_mapping
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled user selection")
                return [], {}
            
            try:
                selected_indices = self.parse_user_selection(selection, len(all_users))
                if selected_indices:
                    # Show what was selected
                    selected_user_info = []
                    selected_regions = set()
                    selected_accounts = set()
                    
                    for idx in selected_indices:
                        user_info = user_mapping[idx]
                        real_user = user_info['real_user']
                        full_name = real_user.get('full_name', user_info['username'])
                        
                        selected_user_info.append({
                            'index': idx,
                            'username': user_info['username'],
                            'full_name': full_name,
                            'account_name': user_info['account_name'],
                            'account_id': user_info['account_id'],
                            'region': user_info['region'],
                            'has_credentials': bool(user_info['access_key'] and user_info['secret_key'])
                        })
                        
                        selected_regions.add(user_info['region'])
                        selected_accounts.add(user_info['account_name'])
                    
                    print(f"\n✅ Selected {len(selected_indices)} users:")
                    print("-" * 80)
                    
                    # Group by account for display
                    by_account = {}
                    for user in selected_user_info:
                        account = user['account_name']
                        if account not in by_account:
                            by_account[account] = []
                        by_account[account].append(user)
                    
                    for account_name, users in by_account.items():
                        account_id = users[0]['account_id']
                        print(f"\n🏦 {account_name} ({account_id}) - {len(users)} users:")
                        for user in users:
                            creds_status = "✅" if user['has_credentials'] else "❌"
                            print(f"   • {user['full_name']} ({user['username']}) in {user['region']} {creds_status}")
                    
                    print("-" * 80)
                    print(f"📊 Selection Summary:")
                    print(f"   👥 Users: {len(selected_indices)}")
                    print(f"   🏦 Accounts: {len(selected_accounts)}")
                    print(f"   🌍 Regions: {len(selected_regions)}")
                    
                    # Check for users without credentials
                    users_without_creds = [u for u in selected_user_info if not u['has_credentials']]
                    if users_without_creds:
                        print(f"   ⚠️  Users without credentials: {len(users_without_creds)}")
                    
                    # Log selection details
                    self.log_operation('INFO', f"Selected users: {[u['username'] for u in selected_user_info]}")
                    self.log_operation('INFO', f"Selection summary: {len(selected_indices)} users, {len(selected_accounts)} accounts, {len(selected_regions)} regions")
                    
                    confirm = input(f"\n🚀 Proceed with these {len(selected_indices)} users? (y/N): ").lower().strip()
                    self.log_operation('INFO', f"User confirmation for user selection: '{confirm}'")
                    
                    if confirm == 'y':
                        return selected_indices, user_mapping
                    else:
                        print("❌ Selection cancelled, please choose again.")
                        self.log_operation('INFO', "User cancelled user selection, requesting new input")
                        continue
                else:
                    print("❌ No valid users selected. Please try again.")
                    self.log_operation('WARNING', "No valid users selected from user input")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                self.log_operation('ERROR', f"Invalid user selection format: {e}")
                continue

    def parse_user_selection(self, selection, max_users):
        """Parse user selection string and return list of user indices"""
        selected_indices = set()
        
        # Split by comma and process each part
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                # Handle range like "1-5"
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start < 1 or end > max_users:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_users})")
                    
                    if start > end:
                        raise ValueError(f"Invalid range {part}: start must be <= end")
                    
                    selected_indices.update(range(start, end + 1))
                    
                except ValueError as e:
                    if "invalid literal" in str(e):
                        raise ValueError(f"Invalid range format: {part}")
                    else:
                        raise
            else:
                # Handle single number
                try:
                    num = int(part)
                    if num < 1 or num > max_users:
                        raise ValueError(f"User number {num} is out of bounds (1-{max_users})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid user number: {part}")
        
        return sorted(list(selected_indices))
    
    def display_instance_menu(self):
        """Display instance type selection menu"""
        allowed_types = self.ami_config['allowed_instance_types']
        default_type = self.ami_config['default_instance_type']
        
        self.log_operation('INFO', f"Displaying instance type menu - {len(allowed_types)} options available")
        
        print("\n🖥️  Available Instance Types:")
        for i, instance_type in enumerate(allowed_types, 1):
            marker = " (default)" if instance_type == default_type else ""
            print(f"  {i}. {instance_type}{marker}")
        
        while True:
            try:
                choice = input(f"\n🔢 Select instance type (1-{len(allowed_types)}) or press Enter for default: ").strip()
                
                self.log_operation('INFO', f"User input for instance type: '{choice}'")
                
                if not choice:
                    self.log_operation('INFO', f"User selected default instance type: {default_type}")
                    return default_type
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(allowed_types):
                    selected_type = allowed_types[choice_num - 1]
                    self.log_operation('INFO', f"User selected instance type: {selected_type}")
                    return selected_type
                else:
                    print(f"❌ Invalid choice. Please enter a number between 1 and {len(allowed_types)}")
                    self.log_operation('WARNING', f"Invalid instance type choice: {choice}")
            except ValueError:
                print("❌ Invalid input. Please enter a number or press Enter for default.")
                self.log_operation('WARNING', f"Invalid instance type input format: {choice}")

    # Add cost estimation display for both scripts:

    def display_cost_estimation(self, instance_type: str, capacity_type: str, node_count: int = 1):
        """Display estimated cost information"""
        # This is a simplified estimation - you'd want to use actual AWS pricing API
        base_costs = {
            't3.micro': 0.0104,
            't3.small': 0.0208,
            't3.medium': 0.0416,
            'c6a.large': 0.0864,
            'c6a.xlarge': 0.1728
        }
        
        base_cost = base_costs.get(instance_type, 0.05)  # Default fallback
        
        if capacity_type.lower() in ['spot', 'SPOT']:
            estimated_cost = base_cost * 0.3  # Spot instances are typically 70% cheaper
            savings = base_cost * 0.7
            print(f"\n💰 Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Spot: ${estimated_cost:.4f}")
            print(f"   Savings: ${savings:.4f} ({70}%)")
            print(f"   Monthly (730 hrs): ${estimated_cost * 730 * node_count:.2f}")
        else:
            print(f"\n💰 Estimated Cost (per hour):")
            print(f"   On-Demand: ${base_cost:.4f}")
            print(f"   Monthly (730 hrs): ${base_cost * 730 * node_count:.2f}")

    def run(self):
        """Main execution method"""
        try:
            self.log_operation('INFO', "🚀 Starting EC2 Instance Creation Session")
            
            print("🚀 EC2 Instance Creation for IAM Users")
            print("=" * 80)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📄 Credentials Source: {self.credentials_file}")
            print(f"📜 User Data Script: {self.userdata_file}")
            print(f"📋 Log File: {self.log_filename}")
            
            # Display credential file info
            if 'created_date' in self.credentials_data:
                cred_time = f"{self.credentials_data['created_date']} {self.credentials_data.get('created_time', '')}"
                print(f"📅 Credentials created: {cred_time}")
                self.log_operation('INFO', f"Using credentials created: {cred_time}")
            if 'created_by' in self.credentials_data:
                print(f"👤 Credentials created by: {self.credentials_data['created_by']}")
            
            print("=" * 80)
            
            # Verify user data file exists and show preview
            if os.path.exists(self.userdata_file):
                file_size = os.path.getsize(self.userdata_file)
                print(f"✅ User data script found: {self.userdata_file}")
                print(f"📏 Script size: {file_size} bytes")
                self.log_operation('INFO', f"User data script verified: {self.userdata_file} ({file_size} bytes)")
            else:
                print(f"❌ User data script not found: {self.userdata_file}")
                self.log_operation('ERROR', f"User data script not found: {self.userdata_file}")
                return
            
            # Step 1: Select accounts to process
            selected_account_indices = self.display_accounts_menu()
            if not selected_account_indices:
                self.log_operation('INFO', "Session cancelled - no accounts selected")
                print("❌ Account selection cancelled")
                return
            
            selected_accounts = self.get_selected_accounts_data(selected_account_indices)
            
            # Step 2: Ask for selection level preference
            print(f"\n🎯 Selection Level:")
            print("=" * 50)
            print("  1. Process ALL users in selected accounts")
            print("  2. Select specific users from selected accounts")
            print("=" * 50)
            
            while True:
                selection_level = input("🔢 Choose selection level (1-2): ").strip()
                self.log_operation('INFO', f"User input for selection level: '{selection_level}'")
                
                if selection_level == '1':
                    # Use all users from selected accounts
                    self.log_operation('INFO', "User chose to process all users in selected accounts")
                    final_accounts = selected_accounts
                    break
                elif selection_level == '2':
                    # Allow user-level selection
                    self.log_operation('INFO', "User chose user-level selection")
                    
                    # Step 3: Select specific users
                    selected_user_indices, user_mapping = self.display_users_menu(selected_accounts)
                    if not selected_user_indices:
                        self.log_operation('INFO', "Session cancelled - no users selected")
                        print("❌ User selection cancelled")
                        return
                    
                    # Convert selected users back to account format
                    final_accounts = self.convert_selected_users_to_accounts(selected_user_indices, user_mapping)
                    break
                else:
                    print("❌ Invalid choice. Please enter 1 or 2.")
                    self.log_operation('WARNING', f"Invalid selection level choice: {selection_level}")
            
            # Select instance type
            instance_type = self.display_instance_menu()

            capacity_type = self.select_capacity_type_ec2()
            
            # Calculate totals for final selection
            total_users = sum(len(account_data.get('users', [])) 
                            for account_data in final_accounts.values())
            
            # Show final confirmation with detailed breakdown
            print(f"\n📊 Final Execution Summary:")
            print("=" * 60)
            print(f"   📈 Selected accounts: {len(final_accounts)}")
            print(f"   👥 Total users: {total_users}")
            print(f"   💻 Instance type: {instance_type}")
            # ADD THIS: Show cost estimation for all instances
            print(f"\n📊 Total Cost Estimation for {total_users} instances:")
            self.display_cost_estimation(instance_type, capacity_type, total_users)
            
            # Show account breakdown
            print(f"\n🏦 Final Account/User Breakdown:")
            for account_name, account_data in final_accounts.items():
                user_count = len(account_data.get('users', []))
                account_id = account_data.get('account_id', 'Unknown')
                print(f"   • {account_name} ({account_id}): {user_count} users")
                
                # Show user details
                for user_data in account_data.get('users', []):
                    username = user_data.get('username', 'unknown')
                    real_user = user_data.get('real_user', {})
                    full_name = real_user.get('full_name', username)
                    region = user_data.get('region', 'unknown')
                    print(f"     - {full_name} ({username}) in {region}")
            
            print(f"\n🔧 Configuration:")
            print(f"   📜 User data: {self.userdata_file}")
            print(f"   📄 Credentials: {self.credentials_file}")
            print(f"   📋 Log file: {self.log_filename}")
            print("=" * 60)
            
            # Log final configuration
            self.log_operation('INFO', f"Final configuration - Accounts: {len(final_accounts)}, Users: {total_users}, Instance type: {instance_type}")
            
            # Final confirmation
            confirm = input(f"\n🚀 Create {total_users} EC2 instances across {len(final_accounts)} accounts? (y/N): ").lower().strip()
            self.log_operation('INFO', f"Final confirmation: '{confirm}'")
            
            if confirm != 'y':
                self.log_operation('INFO', "Session cancelled by user at final confirmation")
                print("❌ Instance creation cancelled")
                return
            
            # Create instances (rest of the method remains the same...)
            print(f"\n🔄 Starting instance creation...")
            self.log_operation('INFO', f"🔄 Beginning instance creation for {total_users} users")
            
            created_instances, failed_instances = self.create_instances_for_selected_accounts(
                final_accounts,
                instance_type=instance_type,
                capacity_type=capacity_type,  # Add this line
                wait_for_running=True
            )
            
            # Display summary (rest remains the same...)
            print(f"\n🎯" * 25 + " CREATION SUMMARY " + "🎯" * 25)
            print("=" * 100)
            print(f"✅ Total instances created: {len(created_instances)}")
            print(f"❌ Total instances failed: {len(failed_instances)}")
            
            self.log_operation('INFO', f"FINAL RESULTS - Created: {len(created_instances)}, Failed: {len(failed_instances)}")
            
            if created_instances:
                print(f"\n✅ Successfully Created Instances:")
                print("-" * 80)
                for instance in created_instances:
                    real_name = instance.get('real_user_info', {}).get('full_name', instance['username'])
                    print(f"   • {real_name} ({instance['username']})")
                    print(f"     📍 Instance: {instance['instance_id']} in {instance['region']}")
                    print(f"     🏦 Account: {instance['account_name']} ({instance['account_id']})")
                    if 'public_ip' in instance and instance['public_ip'] != 'N/A':
                        print(f"     🌐 Public IP: {instance['public_ip']}")
                    print()
            
            if failed_instances:
                print(f"\n❌ Failed Instances:")
                print("-" * 80)
                for failure in failed_instances:
                    print(f"   • {failure.get('real_name', failure['username'])} ({failure['username']})")
                    print(f"     🏦 Account: {failure['account_name']}")
                    print(f"     ❌ Error: {failure['error']}")
                    print()
            
            # Save all reports
            print(f"\n📄 Saving reports...")
            
            # Save user-instance mapping
            mapping_file = self.save_user_instance_mapping(created_instances, failed_instances)
            if mapping_file:
                print(f"✅ User-instance mapping saved to: {mapping_file}")
            
            # Save detailed report
            report_file = self.save_instance_report(created_instances, failed_instances)
            if report_file:
                print(f"✅ Detailed instance report saved to: {report_file}")
            
            print(f"✅ Session log saved to: {self.log_filename}")
            
            # Log final summary
            total_processed = len(created_instances) + len(failed_instances)
            success_rate = (len(created_instances) / total_processed * 100) if total_processed > 0 else 0
            
            self.log_operation('INFO', "=" * 80)
            self.log_operation('INFO', "SESSION COMPLETED SUCCESSFULLY")
            self.log_operation('INFO', f"Total processed: {total_processed}")
            self.log_operation('INFO', f"Successfully created: {len(created_instances)}")
            self.log_operation('INFO', f"Failed: {len(failed_instances)}")
            self.log_operation('INFO', f"Success rate: {success_rate:.1f}%")
            if mapping_file:
                self.log_operation('INFO', f"User-instance mapping file: {mapping_file}")
            if report_file:
                self.log_operation('INFO', f"Detailed report file: {report_file}")
            self.log_operation('INFO', "=" * 80)
            
            print(f"\n🎉 EC2 instance creation completed!")
            print(f"📊 Success rate: {success_rate:.1f}%")
            print("=" * 100)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in main execution: {str(e)}")
            raise
        
def main():
    """Main function"""
    try:
        manager = EC2InstanceManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()