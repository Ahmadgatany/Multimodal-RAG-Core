#!/usr/bin/env python3
"""Test script for Multimodal RAG system"""

import requests
import json
import sys
import random
import string
from pathlib import Path

API_URL = "http://localhost:8000"
TEST_USERNAME = f"testuser_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"
TEST_PASSWORD = "TestPassword123!"

def test_registration():
    """Test user registration"""
    print("\n1. Testing Registration...")
    url = f"{API_URL}/auth/register"
    data = {
        "username": TEST_USERNAME,
        "password": TEST_PASSWORD
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            print(f"✓ Registration successful: {response.status_code}")
            return response.json()
        else:
            print(f"✗ Registration failed: {response.status_code}")
            print(f"  Response: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"✗ Registration error: {e}")
        return None

def test_login(username, password):
    """Test user login"""
    print("\n2. Testing Login...")
    url = f"{API_URL}/auth/login"
    data = {
        "username": username,
        "password": password
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            token = result.get("token")
            print(f"✓ Login successful: {response.status_code}")
            print(f"  Token: {token[:20] if token else 'No token'}...")
            return result
        else:
            print(f"✗ Login failed: {response.status_code}")
            print(f"  Response: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"✗ Login error: {e}")
        return None

def test_chat(token, message):
    """Test chat endpoint"""
    print(f"\n3. Testing Chat: '{message}'...")
    url = f"{API_URL}/chat"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"question": message}  # Changed from "message" to "question"
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        if response.status_code == 200:
            result = response.json()
            chat_response = result.get("answer", result.get("response", "No response"))
            print(f"✓ Chat successful: {response.status_code}")
            print(f"  Response: {chat_response[:150]}")
            return result
        else:
            print(f"✗ Chat failed: {response.status_code}")
            print(f"  Response: {response.text[:300]}")
            return None
    except Exception as e:
        print(f"✗ Chat error: {e}")
        return None

def test_image_vision(token):
    """Test image upload and vision"""
    print("\n4. Testing Image Vision...")
    image_path = Path("E:/GitHup Projects/Multimodal-RAG-Core Project/img.jpeg")
    
    if not image_path.exists():
        print(f"✗ Image not found: {image_path}")
        return False
    
    # Upload image using /chat_with_image endpoint instead
    print("  Uploading and processing image...")
    url = f"{API_URL}/chat_with_image"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        with open(image_path, "rb") as f:
            files = {"image": ("img.jpeg", f, "image/jpeg")}
            data = {"question": "What is the total in QAR shown in this invoice?"}
            response = requests.post(url, files=files, data=data, headers=headers, timeout=30)
        
        if response.status_code == 200:
            print(f"✓ Image vision successful: {response.status_code}")
            result = response.json()
            answer = result.get("answer", result.get("response", "No response"))
            print(f"  Response: {answer}")
            return True
        else:
            print(f"✗ Image vision failed: {response.status_code}")
            print(f"  Response: {response.text[:300]}")
            return False
    except Exception as e:
        print(f"✗ Image vision error: {e}")
        return False

def main():
    print("=" * 60)
    print("Testing Multimodal RAG Core System")
    print("=" * 60)
    
    # Register
    reg_result = test_registration()
    if not reg_result:
        print("\n✗ Registration failed. Aborting...")
        sys.exit(1)
    
    # Login
    login_result = test_login(TEST_USERNAME, TEST_PASSWORD)
    if not login_result:
        print("\n✗ Login failed. Aborting...")
        sys.exit(1)
    
    token = login_result.get("token")
    if not token:
        print("\n✗ No token received. Aborting...")
        sys.exit(1)
    
    # Test chat
    chat_result = test_chat(token, "What is artificial intelligence?")
    
    # Test vision
    vision_result = test_image_vision(token)
    
    print("\n" + "=" * 60)
    print("Test Summary:")
    print("✓ Registration: PASSED")
    print("✓ Login: PASSED")
    print(f"✓ Chat: {'PASSED' if chat_result else 'FAILED'}")
    print(f"✓ Vision: {'PASSED' if vision_result else 'FAILED'}")
    print("=" * 60)

if __name__ == "__main__":
    main()
