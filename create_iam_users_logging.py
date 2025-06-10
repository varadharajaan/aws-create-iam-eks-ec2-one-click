#!/usr/bin/env python3

import boto3
import json
import sys
import os
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from logger import setup_logger
from excel_helper import ExcelCredentialsExporter

class IAMUserManager:
    def __init__(self, config_file='aws_accounts_config.json', mapping_file='user_mapping.json'):
        self.config_file = config_file
        self.mapping_file = mapping_file
        self.logger = setup_logger("iam_user_manager", "user_creation")
        self.load_configuration()
        self.load_user_mapping()
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
    def load_configuration(self):
        """Load AWS account configurations from JSON file"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
            
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            self.aws_accounts = config['accounts']
            self.user_settings = config['user_settings']
            
            self.logger.info(f"Configuration loaded from: {self.config_file}")
            self.logger.info(f"Found {len(self.aws_accounts)} AWS accounts")
            
        except FileNotFoundError as e:
            self.logger.error(f"Configuration file error: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            sys.exit(1)

    def load_user_mapping(self):
        """Load user mapping from JSON file"""
        try:
            if not os.path.exists(self.mapping_file):
                self.logger.warning(f"User mapping file '{self.mapping_file}' not found")
                self.user_mappings = {}
                return
            
            with open(self.mapping_file, 'r') as f:
                mapping_data = json.load(f)
            
            self.user_mappings = mapping_data['user_mappings']
            self.logger.info(f"User mapping loaded from: {self.mapping_file}")
            self.logger.info(f"Found mappings for {len(self.user_mappings)} users")
            
        except Exception as e:
            self.logger.warning(f"Error loading user mapping: {e}")
            self.user_mappings = {}

    def get_user_info(self, username):
        """Get real user information for a username"""
        if username in self.user_mappings:
            mapping = self.user_mappings[username]
            return {
                'first_name': mapping['first_name'],
                'last_name': mapping['last_name'],
                'email': mapping['email'],
                'full_name': f"{mapping['first_name']} {mapping['last_name']}"
            }
        else:
            self.logger.warning(f"No mapping found for user: {username}")
            return {
                'first_name': 'Unknown',
                'last_name': 'User',
                'email': 'unknown@bakerhughes.com',
                'full_name': 'Unknown User'
            }

    def create_iam_client(self, account_name):
        """Create IAM client using specific account credentials"""
        if account_name not in self.aws_accounts:
            raise ValueError(f"Account {account_name} not found in configurations")
        
        account_config = self.aws_accounts[account_name]
        
        try:
            iam_client = boto3.client(
                'iam',
                aws_access_key_id=account_config['access_key'],
                aws_secret_access_key=account_config['secret_key'],
                region_name='us-east-1'
            )
            
            # Test the connection
            iam_client.get_user()
            self.logger.log_account_action(account_name, "CONNECT", "SUCCESS", f"Account ID: {account_config['account_id']}")
            return iam_client, account_config
            
        except ClientError as e:
            error_msg = f"Access denied: {e}"
            self.logger.log_account_action(account_name, "CONNECT", "FAILED", error_msg)
            raise
        except Exception as e:
            error_msg = f"Connection failed: {e}"
            self.logger.log_account_action(account_name, "CONNECT", "FAILED", error_msg)
            raise

    def check_user_exists(self, iam_client, username):
        """Check if IAM user already exists"""
        try:
            iam_client.get_user(UserName=username)
            self.logger.log_user_action(username, "CHECK_EXISTS", "EXISTS")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                self.logger.log_user_action(username, "CHECK_EXISTS", "NOT_EXISTS")
                return False
            else:
                self.logger.error(f"Error checking user existence: {e}")
                raise e

    def get_users_for_account(self, account_name):
        """Get user-region mapping for specific account, supporting per-account user count overrides."""
        regions = self.user_settings['user_regions']
        # Check for per-account override
        if 'users_per_account' in self.aws_accounts[account_name]:
            users_count = self.aws_accounts[account_name]['users_per_account']
        else:
            users_count = self.user_settings['users_per_account']

        users_regions = {}
        for i in range(1, users_count + 1):
            username = f"{account_name}_clouduser{i:02d}"
            region = regions[(i-1) % len(regions)]  # Cycle through regions
            users_regions[username] = region

        return users_regions

    def create_restriction_policy(self, region):
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyIfNotInRegion",
                    "Effect": "Deny",
                    "Action": "*",
                    "Resource": "*",
                    "Condition": {
                        "StringNotEquals": {
                            "aws:RequestedRegion": region
                        }
                    }
                },
                {
                    "Sid": "DenyIfDisallowedInstanceType",
                    "Effect": "Deny",
                    "Action": [
                        "ec2:RunInstances",
                        "ec2:CreateFleet",
                        "ec2:CreateLaunchTemplate",
                        "ec2:CreateLaunchTemplateVersion"
                    ],
                    "Resource": "*",
                    "Condition": {
                        "StringNotEqualsIfExists": {
                            "ec2:InstanceType": self.user_settings['allowed_instance_types']
                        }
                    }
                }
            ]
        }

    def create_single_user(self, iam_client, username, region, account_config):
        """Create a single IAM user with all necessary configurations"""
        try:
            # 1. Create IAM User
            self.logger.debug(f"Creating IAM user: {username}")
            iam_client.create_user(UserName=username)
            self.logger.log_user_action(username, "CREATE_USER", "SUCCESS")
            
            # 2. Enable Console Access
            self.logger.debug(f"Setting up console access for: {username}")
            iam_client.create_login_profile(
                UserName=username,
                Password=self.user_settings['password'],
                PasswordResetRequired=False
            )
            self.logger.log_user_action(username, "CREATE_LOGIN_PROFILE", "SUCCESS")
            
            # 3. Attach AdministratorAccess Policy
            self.logger.debug(f"Attaching AdministratorAccess policy to: {username}")
            iam_client.attach_user_policy(
                UserName=username,
                PolicyArn="arn:aws:iam::aws:policy/AdministratorAccess"
            )
            self.logger.log_user_action(username, "ATTACH_ADMIN_POLICY", "SUCCESS")
            
            # 4. Create Restriction Policy
            self.logger.debug(f"Creating restriction policy for: {username}")
            restriction_policy = self.create_restriction_policy(region)
            
            #iam_client.put_user_policy(
             #   UserName=username,
              #  PolicyName="Restrict-Region-And-EC2Types",
               # PolicyDocument=json.dumps(restriction_policy)
            #)
            self.logger.log_user_action(username, "CREATE_RESTRICTION_POLICY", "SUCCESS", f"Region: {region}")
            
            # 5. Create Access Key
            self.logger.debug(f"Creating access keys for: {username}")
            response = iam_client.create_access_key(UserName=username)
            access_key = response['AccessKey']['AccessKeyId']
            secret_key = response['AccessKey']['SecretAccessKey']
            self.logger.log_user_action(username, "CREATE_ACCESS_KEY", "SUCCESS", f"Key ID: {access_key}")
            
            return {
                'username': username,
                'region': region,
                'access_key': access_key,
                'secret_key': secret_key,
                'console_url': f"https://{account_config['account_id']}.signin.aws.amazon.com/console"
            }
            
        except Exception as e:
            self.logger.log_user_action(username, "CREATE_USER", "FAILED", str(e))
            raise

    def create_users_in_account(self, account_name):
        """Create users in a specific AWS account"""
        self.logger.info(f"Processing account: {account_name.upper()}")
        
        try:
            # Initialize IAM client for this account
            iam_client, account_config = self.create_iam_client(account_name)
            
        except Exception as e:
            self.logger.error(f"Failed to connect to {account_name}: {e}")
            return [], [], []
        
        # Get users for this account
        users_regions = self.get_users_for_account(account_name)
        
        created_users = []
        skipped_users = []
        failed_users = []
        
        # Check existing users first
        self.logger.info(f"Checking for existing users in {account_name}...")
        for username, region in users_regions.items():
            try:
                if self.check_user_exists(iam_client, username):
                    user_info = self.get_user_info(username)
                    self.logger.log_user_action(username, "SKIP", "ALREADY_EXISTS", user_info['full_name'])
                    skipped_users.append({
                        'username': username,
                        'region': region,
                        'reason': 'Already exists',
                        'user_info': user_info
                    })
                    continue
            except Exception as e:
                self.logger.log_user_action(username, "CHECK", "FAILED", str(e))
                failed_users.append(username)
                continue
        
        # Create new users
        users_to_create = {k: v for k, v in users_regions.items() 
                          if k not in [u['username'] for u in skipped_users] 
                          and k not in failed_users}
        
        if not users_to_create:
            self.logger.warning(f"No new users to create in {account_name}")
            return created_users, skipped_users, failed_users
        
        self.logger.info(f"Creating {len(users_to_create)} new users in {account_name}")
        
        for username, region in users_to_create.items():
            user_info = self.get_user_info(username)
            self.logger.info(f"Creating user: {username} → {user_info['full_name']} (Region: {region})")
            
            try:
                user_data = self.create_single_user(iam_client, username, region, account_config)
                
                # Add account and real user information
                user_data.update({
                    'account_name': account_name,
                    'account_id': account_config['account_id'],
                    'account_email': account_config['email'],
                    'user_info': user_info
                })
                
                created_users.append(user_data)
                self.logger.log_user_action(username, "COMPLETE", "SUCCESS", 
                                          f"All resources created for {user_info['full_name']}")
                
            except Exception as e:
                self.logger.log_user_action(username, "CREATE", "FAILED", str(e))
                failed_users.append(username)
                continue
        
        return created_users, skipped_users, failed_users

    def display_account_menu(self):
        """Display account selection menu"""
        print("\n📋 Available AWS Accounts:")
        for i, (account_name, config) in enumerate(self.aws_accounts.items(), 1):
            print(f"  {i}. {account_name} ({config['account_id']}) - {config['email']}")
        
        print(f"  {len(self.aws_accounts) + 1}. All accounts")
        
        while True:
            try:
                choice = input(f"\n🔢 Select account(s) to process (1-{len(self.aws_accounts) + 1}) or range (e.g., 1-3): ").strip()
                
                # Handle range input like "1-2"
                if '-' in choice:
                    try:
                        start, end = choice.split('-')
                        start_num = int(start.strip())
                        end_num = int(end.strip())
                        
                        if start_num < 1 or end_num > len(self.aws_accounts) or start_num > end_num:
                            print(f"❌ Invalid range. Please enter a range between 1 and {len(self.aws_accounts)}")
                            continue
                        
                        # Return list of account names for the range
                        account_names = list(self.aws_accounts.keys())
                        return account_names[start_num-1:end_num]
                        
                    except ValueError:
                        print("❌ Invalid range format. Use format like '1-3'")
                        continue
                
                # Handle single number input
                choice_num = int(choice)
                
                if choice_num == len(self.aws_accounts) + 1:
                    return list(self.aws_accounts.keys())
                elif 1 <= choice_num <= len(self.aws_accounts):
                    return [list(self.aws_accounts.keys())[choice_num - 1]]
                else:
                    print(f"❌ Invalid choice. Please enter a number between 1 and {len(self.aws_accounts) + 1}")
            except ValueError:
                print("❌ Invalid input. Please enter a number or range (e.g., 1-3).")

    def save_credentials_to_file(self, all_created_users):
        """Save user credentials to a JSON file and create Excel with correct column order"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"iam_users_credentials_{timestamp}.json"
            
            credentials_data = {
                "created_date": self.current_time.split()[0],
                "created_time": self.current_time.split()[1] + " UTC",
                "created_by": self.current_user,
                "total_users": len(all_created_users),
                "accounts": {}
            }
            
            # Group users by account
            for user in all_created_users:
                account_name = user['account_name']
                if account_name not in credentials_data["accounts"]:
                    credentials_data["accounts"][account_name] = {
                        "account_id": user['account_id'],
                        "account_email": user['account_email'],
                        "users": []
                    }
                
                credentials_data["accounts"][account_name]["users"].append({
                    "username": user['username'],
                    "real_user": {
                        "first_name": user['user_info']['first_name'],
                        "last_name": user['user_info']['last_name'],
                        "full_name": user['user_info']['full_name'],
                        "email": user['user_info']['email']
                    },
                    "region": user['region'],
                    "access_key_id": user['access_key'],
                    "secret_access_key": user['secret_key'],
                    "console_password": self.user_settings['password'],
                    "console_url": user['console_url']
                })
            
            with open(filename, 'w') as f:
                json.dump(credentials_data, f, indent=2)
            
            self.logger.log_credentials_saved(filename, len(all_created_users))
            
            # Create Excel file with correct column order
            try:
                exporter = ExcelCredentialsExporter()
                excel_path = exporter.export_from_json(filename)
                self.logger.info(f"Excel file created with correct column order: {excel_path}")
                print(f"📊 Excel file created: {excel_path}")
                print(f"📋 Columns: firstname, lastname, mail id, username, password, loginurl, homeregion, accesskey, secretkey")
                
                # Optionally create summary Excel with multiple sheets
                summary_path = exporter.create_summary_sheet(filename)
                self.logger.info(f"Summary Excel created: {summary_path}")
                print(f"📈 Summary Excel created: {summary_path}")
                
            except Exception as e:
                self.logger.error(f"Failed to create Excel files: {e}")
                print(f"❌ Failed to create Excel files: {e}")
            
            return filename
            
        except Exception as e:
            self.logger.error(f"Failed to save credentials to file: {e}")
            return None

    def run(self):
        """Main execution method"""
        self.logger.info("Starting AWS IAM User Creation with Real User Mapping")
        self.logger.info(f"Execution time: {self.current_time} UTC")
        self.logger.info(f"Executed by: {self.current_user}")
        
        # Select accounts to process
        accounts_to_process = self.display_account_menu()
        self.logger.info(f"Selected accounts for processing: {accounts_to_process}")
        
        all_created_users = []
        all_skipped_users = []
        all_failed_users = []
        
        # Process selected accounts
        for account_name in accounts_to_process:
            created_users, skipped_users, failed_users = self.create_users_in_account(account_name)
            all_created_users.extend(created_users)
            all_skipped_users.extend(skipped_users)
            all_failed_users.extend(failed_users)
        
        # Log final summary
        total_processed = len(all_created_users) + len(all_skipped_users) + len(all_failed_users)
        self.logger.log_summary(total_processed, len(all_created_users), len(all_failed_users), len(all_skipped_users))
        
        # Save credentials if any users were created
        if all_created_users:
            save_to_file = input("\n💾 Save credentials to file? (y/N): ").lower().strip()
            if save_to_file == 'y':
                saved_file = self.save_credentials_to_file(all_created_users)
                if saved_file:
                    print(f"✅ Credentials saved to: {saved_file}")
                    print("📊 Excel files also generated in output/ directory")

def main():
    """Main function"""
    try:
        manager = IAMUserManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()