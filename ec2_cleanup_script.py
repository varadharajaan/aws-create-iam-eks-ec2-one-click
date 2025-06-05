#!/usr/bin/env python3

import boto3
import json
import sys
import os
import time
import glob
import re
from datetime import datetime
from botocore.exceptions import ClientError, BotoCoreError
from logger import setup_logger

class EC2CleanupManager:
    def __init__(self):
        self.logger = setup_logger("ec2_cleanup_manager", "ec2_cleanup")
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_user = "varadharajaan"
        
        # Generate timestamp for output files
        self.execution_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Initialize log file
        self.setup_detailed_logging()
        
        # Storage for cleanup results
        self.cleanup_results = {
            'processed_files': [],
            'deleted_instances': [],
            'deleted_security_groups': [],
            'failed_deletions': [],
            'skipped_instances': []
        }

    def setup_detailed_logging(self):
        """Setup detailed logging to file"""
        try:
            self.log_filename = f"ec2_cleanup_log_{self.execution_timestamp}.log"
            
            # Create a file handler for detailed logging
            import logging
            
            # Create logger for detailed operations
            self.operation_logger = logging.getLogger('ec2_cleanup_operations')
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
            self.operation_logger.info("EC2 Cleanup Session Started")
            self.operation_logger.info("=" * 80)
            self.operation_logger.info(f"Execution Time: {self.current_time} UTC")
            self.operation_logger.info(f"Executed By: {self.current_user}")
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

    def find_instance_report_files(self):
        """Find all EC2 instance report files"""
        try:
            # Look for instance report files
            patterns = [
                "ec2_instances_report_*.json",
                "iam_user_instance_mapping_*.json"
            ]
            
            all_files = []
            for pattern in patterns:
                matching_files = glob.glob(pattern)
                all_files.extend(matching_files)
            
            if not all_files:
                self.log_operation('ERROR', f"No EC2 report files found matching patterns: {patterns}")
                return []
            
            # Remove duplicates and sort by timestamp
            unique_files = list(set(all_files))
            
            self.log_operation('INFO', f"Found {len(unique_files)} EC2 report files:")
            
            # Extract timestamps and sort
            file_timestamps = []
            for file_path in unique_files:
                # Extract timestamp from filename
                match = re.search(r'(\d{8}_\d{6})\.json', file_path)
                if match:
                    timestamp_str = match.group(1)
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        file_timestamps.append((file_path, timestamp, timestamp_str))
                        self.log_operation('INFO', f"  📄 {file_path} (timestamp: {timestamp_str})")
                    except ValueError as e:
                        self.log_operation('WARNING', f"  ⚠️  {file_path} has invalid timestamp format: {e}")
                else:
                    self.log_operation('WARNING', f"  ⚠️  {file_path} doesn't match expected timestamp pattern")
            
            if not file_timestamps:
                self.log_operation('ERROR', "No valid report files with proper timestamp format found")
                return []
            
            # Sort by timestamp (newest first)
            file_timestamps.sort(key=lambda x: x[1], reverse=True)
            
            return file_timestamps
            
        except Exception as e:
            self.log_operation('ERROR', f"Error finding report files: {e}")
            return []

    def display_report_files_menu(self, file_timestamps):
        """Display available report files and return selection"""
        if not file_timestamps:
            return []
        
        print(f"\n📄 Available EC2 Report Files ({len(file_timestamps)} total):")
        print("=" * 100)
        
        for i, (file_path, timestamp, timestamp_str) in enumerate(file_timestamps, 1):
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            file_date = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"  {i:2}. {file_path}")
            print(f"      📅 Created: {file_date}")
            print(f"      📏 Size: {file_size:,} bytes")
            print(f"      🔤 Timestamp: {timestamp_str}")
            print()
        
        print("=" * 100)
        print(f"📝 Selection Options:")
        print(f"   • Single files: 1,3,5")
        print(f"   • Ranges: 1-{len(file_timestamps)} (files 1 through {len(file_timestamps)})")
        print(f"   • Mixed: 1-2,4 (files 1, 2, and 4)")
        print(f"   • All files: 'all' or press Enter")
        print(f"   • Cancel: 'cancel' or 'quit'")
        
        while True:
            selection = input(f"\n🔢 Select report files to process: ").strip()
            
            self.log_operation('INFO', f"User input for file selection: '{selection}'")
            
            if not selection or selection.lower() == 'all':
                self.log_operation('INFO', "User selected all files")
                return list(range(1, len(file_timestamps) + 1))
            
            if selection.lower() in ['cancel', 'quit', 'exit']:
                self.log_operation('INFO', "User cancelled file selection")
                return []
            
            try:
                selected_indices = self.parse_selection(selection, len(file_timestamps))
                if selected_indices:
                    # Show what was selected
                    selected_files = []
                    for idx in selected_indices:
                        file_path, timestamp, timestamp_str = file_timestamps[idx - 1]
                        selected_files.append({
                            'path': file_path,
                            'timestamp': timestamp_str,
                            'date': timestamp.strftime("%Y-%m-%d %H:%M:%S")
                        })
                    
                    print(f"\n✅ Selected {len(selected_indices)} files:")
                    print("-" * 80)
                    for file_info in selected_files:
                        print(f"   • {file_info['path']}")
                        print(f"     📅 {file_info['date']}")
                    
                    confirm = input(f"\n🚀 Proceed with cleanup using these {len(selected_indices)} files? (y/N): ").lower().strip()
                    self.log_operation('INFO', f"User confirmation for file selection: '{confirm}'")
                    
                    if confirm == 'y':
                        return selected_indices
                    else:
                        print("❌ Selection cancelled, please choose again.")
                        continue
                else:
                    print("❌ No valid files selected. Please try again.")
                    continue
                    
            except ValueError as e:
                print(f"❌ Invalid selection: {e}")
                print("   Please use format like: 1,3,5 or 1-5 or 1-3,5,7-9")
                self.log_operation('ERROR', f"Invalid file selection format: {e}")
                continue

    def parse_selection(self, selection, max_items):
        """Parse selection string and return list of indices"""
        selected_indices = set()
        
        parts = [part.strip() for part in selection.split(',')]
        
        for part in parts:
            if not part:
                continue
                
            if '-' in part:
                try:
                    start_str, end_str = part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    
                    if start < 1 or end > max_items:
                        raise ValueError(f"Range {part} is out of bounds (1-{max_items})")
                    
                    if start > end:
                        raise ValueError(f"Invalid range {part}: start must be <= end")
                    
                    selected_indices.update(range(start, end + 1))
                    
                except ValueError as e:
                    if "invalid literal" in str(e):
                        raise ValueError(f"Invalid range format: {part}")
                    else:
                        raise
            else:
                try:
                    num = int(part)
                    if num < 1 or num > max_items:
                        raise ValueError(f"Number {num} is out of bounds (1-{max_items})")
                    selected_indices.add(num)
                except ValueError:
                    raise ValueError(f"Invalid number: {part}")
        
        return sorted(list(selected_indices))

    def load_report_file(self, file_path):
        """Load and parse a report file"""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Report file not found: {file_path}")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.log_operation('INFO', f"✅ Successfully loaded report file: {file_path}")
            
            # Extract instances from different file formats
            instances = []
            
            # Check if it's an instance report file
            if 'created_instances' in data:
                instances.extend(data['created_instances'])
                self.log_operation('INFO', f"Found {len(data['created_instances'])} instances in created_instances")
            
            # Check if it's a mapping file with successful mappings
            if 'successful_mappings' in data:
                for username, mapping_info in data['successful_mappings'].items():
                    instance_info = {
                        'instance_id': mapping_info.get('instance_id'),
                        'region': mapping_info.get('region'),
                        'username': username,
                        'account_name': mapping_info.get('account_name'),
                        'account_id': mapping_info.get('account_id'),
                        'security_group_id': None,  # We'll try to find this
                        'source_file': file_path,
                        'source_type': 'mapping_file'
                    }
                    instances.append(instance_info)
                self.log_operation('INFO', f"Found {len(data['successful_mappings'])} instances in successful_mappings")
            
            # Check if it's a detailed report with instance data
            if 'detailed_info' in data and 'successful_instances' in data['detailed_info']:
                instances.extend(data['detailed_info']['successful_instances'])
                self.log_operation('INFO', f"Found {len(data['detailed_info']['successful_instances'])} instances in detailed_info")
            
            # Add source file info to each instance
            for instance in instances:
                if 'source_file' not in instance:
                    instance['source_file'] = file_path
                if 'source_type' not in instance:
                    instance['source_type'] = 'report_file'
            
            self.log_operation('INFO', f"Total instances extracted from {file_path}: {len(instances)}")
            return instances
            
        except FileNotFoundError as e:
            self.log_operation('ERROR', f"File not found: {e}")
            return []
        except json.JSONDecodeError as e:
            self.log_operation('ERROR', f"Invalid JSON in {file_path}: {e}")
            return []
        except Exception as e:
            self.log_operation('ERROR', f"Error loading {file_path}: {e}")
            return []

    def create_ec2_client(self, access_key, secret_key, region):
        """Create EC2 client using IAM user credentials"""
        try:
            ec2_client = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            
            # Test the connection
            ec2_client.describe_regions(RegionNames=[region])
            return ec2_client
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to create EC2 client for {region}: {e}")
            raise

    def get_credentials_for_instance(self, instance):
        """Get AWS credentials for an instance from the original credentials file"""
        try:
            # Try to find the original credentials file used
            source_file = instance.get('source_file', '')
            username = instance.get('username', '')
            
            if not username:
                self.log_operation('WARNING', f"No username found for instance {instance.get('instance_id', 'unknown')}")
                return None, None
            
            # Look for credentials files
            cred_patterns = ["iam_users_credentials_*.json"]
            cred_files = []
            for pattern in cred_patterns:
                cred_files.extend(glob.glob(pattern))
            
            if not cred_files:
                self.log_operation('ERROR', "No credentials files found")
                return None, None
            
            # Sort by timestamp and try the latest first
            cred_files_with_timestamps = []
            for file_path in cred_files:
                match = re.search(r'(\d{8}_\d{6})\.json', file_path)
                if match:
                    timestamp_str = match.group(1)
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                        cred_files_with_timestamps.append((file_path, timestamp))
                    except ValueError:
                        continue
            
            cred_files_with_timestamps.sort(key=lambda x: x[1], reverse=True)
            
            # Try to find credentials for the user
            for cred_file, _ in cred_files_with_timestamps:
                try:
                    with open(cred_file, 'r', encoding='utf-8') as f:
                        cred_data = json.load(f)
                    
                    # Search through accounts for the user
                    if 'accounts' in cred_data:
                        for account_name, account_data in cred_data['accounts'].items():
                            for user_data in account_data.get('users', []):
                                if user_data.get('username') == username:
                                    access_key = user_data.get('access_key_id')
                                    secret_key = user_data.get('secret_access_key')
                                    if access_key and secret_key:
                                        self.log_operation('INFO', f"Found credentials for {username} in {cred_file}")
                                        return access_key, secret_key
                    
                except Exception as e:
                    self.log_operation('WARNING', f"Error reading credentials file {cred_file}: {e}")
                    continue
            
            self.log_operation('ERROR', f"No credentials found for user {username}")
            return None, None
            
        except Exception as e:
            self.log_operation('ERROR', f"Error getting credentials for instance: {e}")
            return None, None

    def check_instance_exists(self, ec2_client, instance_id):
        """Check if an EC2 instance exists and get its current state"""
        try:
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            
            if response['Reservations']:
                instance = response['Reservations'][0]['Instances'][0]
                state = instance['State']['Name']
                
                self.log_operation('INFO', f"Instance {instance_id} exists with state: {state}")
                return True, state, instance
            else:
                self.log_operation('INFO', f"Instance {instance_id} not found")
                return False, None, None
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidInstanceID.NotFound':
                self.log_operation('INFO', f"Instance {instance_id} does not exist")
                return False, None, None
            else:
                self.log_operation('ERROR', f"Error checking instance {instance_id}: {e}")
                raise
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error checking instance {instance_id}: {e}")
            raise

    def terminate_instance(self, ec2_client, instance_id, wait_for_termination=True):
        """Terminate an EC2 instance"""
        try:
            self.log_operation('INFO', f"Terminating instance {instance_id}")
            
            response = ec2_client.terminate_instances(InstanceIds=[instance_id])
            
            current_state = response['TerminatingInstances'][0]['CurrentState']['Name']
            previous_state = response['TerminatingInstances'][0]['PreviousState']['Name']
            
            self.log_operation('INFO', f"Instance {instance_id} termination initiated: {previous_state} → {current_state}")
            
            if wait_for_termination:
                self.log_operation('INFO', f"Waiting for instance {instance_id} to terminate...")
                
                start_time = time.time()
                timeout = 300  # 5 minutes
                
                while time.time() - start_time < timeout:
                    try:
                        exists, state, _ = self.check_instance_exists(ec2_client, instance_id)
                        
                        if not exists or state == 'terminated':
                            elapsed = int(time.time() - start_time)
                            self.log_operation('INFO', f"✅ Instance {instance_id} terminated successfully (took {elapsed}s)")
                            return True
                        
                        if state in ['terminating']:
                            time.sleep(10)
                            continue
                        else:
                            self.log_operation('WARNING', f"Instance {instance_id} in unexpected state: {state}")
                            time.sleep(10)
                            continue
                            
                    except Exception as e:
                        self.log_operation('ERROR', f"Error waiting for termination of {instance_id}: {e}")
                        break
                
                self.log_operation('ERROR', f"Timeout waiting for instance {instance_id} to terminate")
                return False
            
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Failed to terminate instance {instance_id}: {e}")
            raise

    def find_security_groups_for_instance(self, ec2_client, instance_id, username):
        """Find security groups associated with an instance or username"""
        try:
            security_groups = []
            
            # First, try to get security groups from the instance if it still exists
            try:
                exists, state, instance_data = self.check_instance_exists(ec2_client, instance_id)
                if exists and instance_data:
                    for sg in instance_data.get('SecurityGroups', []):
                        security_groups.append(sg['GroupId'])
                    self.log_operation('INFO', f"Found {len(security_groups)} security groups from instance {instance_id}")
            except:
                pass
            
            # Also search for security groups by naming pattern
            try:
                sg_name_pattern = f"{username}-all-traffic-sg"
                response = ec2_client.describe_security_groups(
                    Filters=[
                        {'Name': 'group-name', 'Values': [sg_name_pattern]}
                    ]
                )
                
                for sg in response['SecurityGroups']:
                    sg_id = sg['GroupId']
                    if sg_id not in security_groups:
                        security_groups.append(sg_id)
                        self.log_operation('INFO', f"Found security group by name pattern: {sg_id} ({sg_name_pattern})")
                
            except Exception as e:
                self.log_operation('WARNING', f"Error searching for security groups by name: {e}")
            
            return security_groups
            
        except Exception as e:
            self.log_operation('ERROR', f"Error finding security groups for instance {instance_id}: {e}")
            return []

    def delete_security_group(self, ec2_client, sg_id):
        """Delete a security group"""
        try:
            self.log_operation('INFO', f"Deleting security group {sg_id}")
            
            # Check if security group exists and get details
            try:
                response = ec2_client.describe_security_groups(GroupIds=[sg_id])
                sg_info = response['SecurityGroups'][0]
                sg_name = sg_info['GroupName']
                vpc_id = sg_info['VpcId']
                
                self.log_operation('INFO', f"Security group {sg_id} details: name={sg_name}, vpc={vpc_id}")
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidGroupId.NotFound':
                    self.log_operation('INFO', f"Security group {sg_id} does not exist")
                    return True
                else:
                    raise
            
            # Attempt to delete the security group
            ec2_client.delete_security_group(GroupId=sg_id)
            self.log_operation('INFO', f"✅ Successfully deleted security group {sg_id}")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidGroupId.NotFound':
                self.log_operation('INFO', f"Security group {sg_id} does not exist")
                return True
            elif error_code == 'DependencyViolation':
                self.log_operation('WARNING', f"Cannot delete security group {sg_id}: still in use by other resources")
                return False
            else:
                self.log_operation('ERROR', f"Failed to delete security group {sg_id}: {e}")
                return False
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error deleting security group {sg_id}: {e}")
            return False

    def cleanup_instance(self, instance_info):
        """Cleanup a single instance and its security groups"""
        try:
            instance_id = instance_info.get('instance_id')
            region = instance_info.get('region')
            username = instance_info.get('username', 'unknown')
            account_name = instance_info.get('account_name', 'unknown')
            
            if not instance_id or not region:
                self.log_operation('ERROR', f"Missing instance_id or region for {username}")
                return False
            
            self.log_operation('INFO', f"🧹 Starting cleanup for instance {instance_id} ({username}) in {region}")
            
            # Get credentials for this user
            access_key, secret_key = self.get_credentials_for_instance(instance_info)
            if not access_key or not secret_key:
                self.log_operation('ERROR', f"No credentials found for {username}, skipping cleanup")
                self.cleanup_results['failed_deletions'].append({
                    'instance_id': instance_id,
                    'username': username,
                    'region': region,
                    'account_name': account_name,
                    'error': 'No credentials found'
                })
                return False
            
            # Create EC2 client
            try:
                ec2_client = self.create_ec2_client(access_key, secret_key, region)
            except Exception as e:
                self.log_operation('ERROR', f"Failed to create EC2 client for {username}: {e}")
                self.cleanup_results['failed_deletions'].append({
                    'instance_id': instance_id,
                    'username': username,
                    'region': region,
                    'account_name': account_name,
                    'error': f'Failed to create EC2 client: {str(e)}'
                })
                return False
            
            # Check if instance exists
            exists, state, instance_data = self.check_instance_exists(ec2_client, instance_id)
            
            if not exists:
                self.log_operation('INFO', f"Instance {instance_id} does not exist, skipping to security group cleanup")
                self.cleanup_results['skipped_instances'].append({
                    'instance_id': instance_id,
                    'username': username,
                    'region': region,
                    'account_name': account_name,
                    'reason': 'Instance does not exist'
                })
            else:
                if state == 'terminated':
                    self.log_operation('INFO', f"Instance {instance_id} already terminated")
                    self.cleanup_results['skipped_instances'].append({
                        'instance_id': instance_id,
                        'username': username,
                        'region': region,
                        'account_name': account_name,
                        'reason': 'Already terminated'
                    })
                else:
                    # Terminate the instance
                    try:
                        success = self.terminate_instance(ec2_client, instance_id, wait_for_termination=True)
                        if success:
                            self.cleanup_results['deleted_instances'].append({
                                'instance_id': instance_id,
                                'username': username,
                                'region': region,
                                'account_name': account_name,
                                'previous_state': state
                            })
                        else:
                            raise Exception("Termination failed or timed out")
                    except Exception as e:
                        self.log_operation('ERROR', f"Failed to terminate instance {instance_id}: {e}")
                        self.cleanup_results['failed_deletions'].append({
                            'instance_id': instance_id,
                            'username': username,
                            'region': region,
                            'account_name': account_name,
                            'error': f'Termination failed: {str(e)}'
                        })
                        return False
            
            # Find and delete security groups
            security_groups = self.find_security_groups_for_instance(ec2_client, instance_id, username)
            
            if security_groups:
                self.log_operation('INFO', f"Found {len(security_groups)} security groups for cleanup: {security_groups}")
                
                # Wait a bit for instance termination to complete before deleting security groups
                if exists and state != 'terminated':
                    self.log_operation('INFO', "Waiting 30 seconds for instance termination to complete before deleting security groups")
                    time.sleep(30)
                
                for sg_id in security_groups:
                    try:
                        success = self.delete_security_group(ec2_client, sg_id)
                        if success:
                            self.cleanup_results['deleted_security_groups'].append({
                                'security_group_id': sg_id,
                                'instance_id': instance_id,
                                'username': username,
                                'region': region,
                                'account_name': account_name
                            })
                        else:
                            self.cleanup_results['failed_deletions'].append({
                                'instance_id': instance_id,
                                'username': username,
                                'region': region,
                                'account_name': account_name,
                                'error': f'Failed to delete security group {sg_id}'
                            })
                    except Exception as e:
                        self.log_operation('ERROR', f"Error deleting security group {sg_id}: {e}")
                        self.cleanup_results['failed_deletions'].append({
                            'instance_id': instance_id,
                            'username': username,
                            'region': region,
                            'account_name': account_name,
                            'error': f'Security group deletion error: {str(e)}'
                        })
            else:
                self.log_operation('INFO', f"No security groups found for cleanup for instance {instance_id}")
            
            self.log_operation('INFO', f"✅ Completed cleanup for instance {instance_id} ({username})")
            return True
            
        except Exception as e:
            self.log_operation('ERROR', f"Unexpected error during cleanup of instance {instance_id}: {e}")
            self.cleanup_results['failed_deletions'].append({
                'instance_id': instance_info.get('instance_id', 'unknown'),
                'username': instance_info.get('username', 'unknown'),
                'region': instance_info.get('region', 'unknown'),
                'account_name': instance_info.get('account_name', 'unknown'),
                'error': f'Unexpected error: {str(e)}'
            })
            return False

    def save_cleanup_report(self):
        """Save cleanup results to a JSON report"""
        try:
            report_filename = f"ec2_cleanup_report_{self.execution_timestamp}.json"
            
            report_data = {
                "metadata": {
                    "cleanup_date": self.current_time.split()[0],
                    "cleanup_time": self.current_time.split()[1],
                    "cleaned_by": self.current_user,
                    "execution_timestamp": self.execution_timestamp,
                    "log_file": self.log_filename
                },
                "summary": {
                    "total_files_processed": len(self.cleanup_results['processed_files']),
                    "total_instances_deleted": len(self.cleanup_results['deleted_instances']),
                    "total_instances_skipped": len(self.cleanup_results['skipped_instances']),
                    "total_security_groups_deleted": len(self.cleanup_results['deleted_security_groups']),
                    "total_failed_deletions": len(self.cleanup_results['failed_deletions']),
                    "files_processed": [f['file_path'] for f in self.cleanup_results['processed_files']]
                },
                "detailed_results": self.cleanup_results
            }
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, default=str)
            
            self.log_operation('INFO', f"✅ Cleanup report saved to: {report_filename}")
            return report_filename
            
        except Exception as e:
            self.log_operation('ERROR', f"❌ Failed to save cleanup report: {e}")
            return None

    def run(self):
        """Main execution method"""
        try:
            self.log_operation('INFO', "🧹 Starting EC2 Cleanup Session")
            
            print("🧹 EC2 Instance and Security Group Cleanup")
            print("=" * 80)
            print(f"📅 Execution Date/Time: {self.current_time} UTC")
            print(f"👤 Executed by: {self.current_user}")
            print(f"📋 Log File: {self.log_filename}")
            print("=" * 80)
            
            # Find report files
            file_timestamps = self.find_instance_report_files()
            if not file_timestamps:
                print("❌ No EC2 report files found. Nothing to cleanup.")
                return
            
            # Select files to process
            selected_indices = self.display_report_files_menu(file_timestamps)
            if not selected_indices:
                print("❌ No files selected for cleanup")
                return
            
            # Load instances from selected files
            all_instances = []
            for idx in selected_indices:
                file_path, timestamp, timestamp_str = file_timestamps[idx - 1]
                
                self.log_operation('INFO', f"Processing file: {file_path}")
                instances = self.load_report_file(file_path)
                
                self.cleanup_results['processed_files'].append({
                    'file_path': file_path,
                    'timestamp': timestamp_str,
                    'instances_found': len(instances)
                })
                
                all_instances.extend(instances)
            
            if not all_instances:
                print("❌ No instances found in selected files")
                return
            
            # Remove duplicates based on instance_id
            unique_instances = {}
            for instance in all_instances:
                instance_id = instance.get('instance_id')
                if instance_id and instance_id not in unique_instances:
                    unique_instances[instance_id] = instance
            
            instances_to_cleanup = list(unique_instances.values())
            
            print(f"\n📊 Cleanup Summary:")
            print("=" * 60)
            print(f"   📄 Files processed: {len(selected_indices)}")
            print(f"   💻 Total instances found: {len(all_instances)}")
            print(f"   🔧 Unique instances to cleanup: {len(instances_to_cleanup)}")
            
            # Group by region and account for display
            by_region = {}
            by_account = {}
            
            for instance in instances_to_cleanup:
                region = instance.get('region', 'unknown')
                account = instance.get('account_name', 'unknown')
                
                by_region[region] = by_region.get(region, 0) + 1
                by_account[account] = by_account.get(account, 0) + 1
            
            print(f"   🌍 Regions: {len(by_region)} ({', '.join(f'{r}({c})' for r, c in sorted(by_region.items()))})")
            print(f"   🏦 Accounts: {len(by_account)} ({', '.join(f'{a}({c})' for a, c in sorted(by_account.items()))})")
            print("=" * 60)
            
            # Final confirmation
            confirm = input(f"\n⚠️  DANGER: This will DELETE {len(instances_to_cleanup)} EC2 instances and their security groups!\n"
                          f"🚨 Are you absolutely sure? Type 'DELETE' to confirm: ").strip()
            
            self.log_operation('INFO', f"User confirmation: '{confirm}'")
            
            if confirm != 'DELETE':
                self.log_operation('INFO', "Cleanup cancelled by user")
                print("❌ Cleanup cancelled - confirmation not provided")
                return
            
            # Start cleanup process
            print(f"\n🔄 Starting cleanup of {len(instances_to_cleanup)} instances...")
            self.log_operation('INFO', f"🔄 Beginning cleanup of {len(instances_to_cleanup)} instances")
            
            successful_cleanups = 0
            
            for i, instance in enumerate(instances_to_cleanup, 1):
                instance_id = instance.get('instance_id', 'unknown')
                username = instance.get('username', 'unknown')
                real_name = instance.get('real_user_info', {}).get('full_name', username)
                region = instance.get('region', 'unknown')
                account_name = instance.get('account_name', 'unknown')
                
                print(f"\n[{i}/{len(instances_to_cleanup)}] Cleaning up: {real_name} ({username})")
                print(f"    📍 Instance: {instance_id}")
                print(f"    🌍 Region: {region}")
                print(f"    🏦 Account: {account_name}")
                
                try:
                    success = self.cleanup_instance(instance)
                    if success:
                        successful_cleanups += 1
                        print(f"    ✅ Cleanup completed")
                    else:
                        print(f"    ❌ Cleanup failed")
                        
                except Exception as e:
                    print(f"    ❌ Cleanup error: {e}")
                    self.log_operation('ERROR', f"Error cleaning up instance {instance_id}: {e}")
                
                print("-" * 60)
            
            # Display final results
            print(f"\n🎯" + "="*25 + " CLEANUP SUMMARY " + "="*25)
            print(f"✅ Successful cleanups: {successful_cleanups}")
            print(f"📄 Files processed: {len(selected_indices)}")
            print(f"💻 Instances deleted: {len(self.cleanup_results['deleted_instances'])}")
            print(f"⏭️  Instances skipped: {len(self.cleanup_results['skipped_instances'])}")
            print(f"🔒 Security groups deleted: {len(self.cleanup_results['deleted_security_groups'])}")
            print(f"❌ Failed deletions: {len(self.cleanup_results['failed_deletions'])}")
            
            self.log_operation('INFO', f"CLEANUP COMPLETED - Success: {successful_cleanups}/{len(instances_to_cleanup)}")
            
            # Show detailed results
            if self.cleanup_results['deleted_instances']:
                print(f"\n✅ Deleted Instances:")
                for instance in self.cleanup_results['deleted_instances']:
                    print(f"   • {instance['instance_id']} ({instance['username']}) in {instance['region']}")
            
            if self.cleanup_results['skipped_instances']:
                print(f"\n⏭️  Skipped Instances:")
                for instance in self.cleanup_results['skipped_instances']:
                    print(f"   • {instance['instance_id']} ({instance['username']}) - {instance['reason']}")
            
            if self.cleanup_results['failed_deletions']:
                print(f"\n❌ Failed Deletions:")
                for failure in self.cleanup_results['failed_deletions']:
                    print(f"   • {failure['instance_id']} ({failure['username']}) - {failure['error']}")
            
            # Save cleanup report
            print(f"\n📄 Saving cleanup report...")
            report_file = self.save_cleanup_report()
            if report_file:
                print(f"✅ Cleanup report saved to: {report_file}")
            
            print(f"✅ Session log saved to: {self.log_filename}")
            
            success_rate = (successful_cleanups / len(instances_to_cleanup) * 100) if instances_to_cleanup else 0
            print(f"\n🎉 EC2 cleanup completed!")
            print(f"📊 Success rate: {success_rate:.1f}%")
            print("=" * 80)
            
        except Exception as e:
            self.log_operation('ERROR', f"FATAL ERROR in cleanup execution: {str(e)}")
            raise

def main():
    """Main function"""
    try:
        manager = EC2CleanupManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\n❌ Cleanup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()