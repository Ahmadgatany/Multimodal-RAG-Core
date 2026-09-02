# Test the entire RAG system

$API_URL = "http://localhost:8000"
$username = "testuser_$(Get-Random)"
$password = "TestPassword123!"

Write-Host "=== Testing Multimodal RAG System ===" -ForegroundColor Cyan
Write-Host "Username: $username" -ForegroundColor Yellow
Write-Host ""

# 1. Register Account
Write-Host "1. Registering account..." -ForegroundColor Yellow
$regBody = @{
    username = $username
    password = $password
} | ConvertTo-Json

try {
    $regResponse = Invoke-WebRequest -Uri "$API_URL/auth/register" `
        -Method POST `
        -ContentType "application/json" `
        -Body $regBody `
        -TimeoutSec 10
    
    $regData = $regResponse.Content | ConvertFrom-Json
    Write-Host "✓ Registration successful" -ForegroundColor Green
    Write-Host "  Response: $($regResponse.StatusCode)" -ForegroundColor Gray
} catch {
    Write-Host "✗ Registration failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 2. Login
Write-Host ""
Write-Host "2. Logging in..." -ForegroundColor Yellow
$loginBody = @{
    username = $username
    password = $password
} | ConvertTo-Json

try {
    $loginResponse = Invoke-WebRequest -Uri "$API_URL/auth/login" `
        -Method POST `
        -ContentType "application/json" `
        -Body $loginBody `
        -TimeoutSec 10
    
    $loginData = $loginResponse.Content | ConvertFrom-Json
    $accessToken = $loginData.token
    $refreshToken = $loginData.refresh_token
    
    Write-Host "✓ Login successful" -ForegroundColor Green
    Write-Host "  Token: $($accessToken.Substring(0, 20))..." -ForegroundColor Gray
} catch {
    Write-Host "✗ Login failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 3. Upload and test with PDF
Write-Host ""
Write-Host "3. Testing PDF upload and chat..." -ForegroundColor Yellow

# Create a simple test PDF
Write-Host "  Creating test PDF..." -ForegroundColor Gray
$testPdfPath = "$env:TEMP\test_document.pdf"
@"
This is a test document for the RAG system.
It contains information about artificial intelligence.
AI is transforming industries and reshaping how people work.
Modern AI can understand language, recognize images, and make predictions.
"@ | Out-File "$env:TEMP\test_document.txt"

# Try to upload PDF
Write-Host "  Uploading PDF..." -ForegroundColor Gray
$headers = @{ "Authorization" = "Bearer $accessToken" }

try {
    $fileContent = [System.IO.File]::ReadAllBytes("$env:TEMP\test_document.txt")
    $fileBom = [System.Text.Encoding]::UTF8.GetString([System.Text.Encoding]::UTF8.GetPreamble())
    
    # Create multipart form
    $boundary = [System.Guid]::NewGuid().ToString()
    $LF = "`r`n"
    $body = ([System.Text.Encoding]::UTF8.GetBytes("--$boundary$LF"))
    $body += [System.Text.Encoding]::UTF8.GetBytes("Content-Disposition: form-data; name=`"file`"; filename=`"test.txt`"$LF")
    $body += [System.Text.Encoding]::UTF8.GetBytes("Content-Type: text/plain$LF$LF")
    $body += [System.IO.File]::ReadAllBytes("$env:TEMP\test_document.txt")
    $body += [System.Text.Encoding]::UTF8.GetBytes("$LF--$boundary--$LF")
    
    $uploadResponse = Invoke-WebRequest -Uri "$API_URL/upload" `
        -Method POST `
        -Headers $headers `
        -ContentType "multipart/form-data; boundary=`"$boundary`"" `
        -Body $body `
        -TimeoutSec 30
    
    Write-Host "✓ File upload successful" -ForegroundColor Green
    $uploadData = $uploadResponse.Content | ConvertFrom-Json
    Write-Host "  File ID: $($uploadData.file_id)" -ForegroundColor Gray
} catch {
    Write-Host "✗ File upload failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  This might be expected if file endpoint requires different setup" -ForegroundColor Gray
}

# 4. Test chat endpoint
Write-Host ""
Write-Host "4. Testing chat endpoint..." -ForegroundColor Yellow
$chatBody = @{
    message = "What is artificial intelligence?"
} | ConvertTo-Json

try {
    $chatResponse = Invoke-WebRequest -Uri "$API_URL/chat" `
        -Method POST `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $chatBody `
        -TimeoutSec 30
    
    Write-Host "✓ Chat successful" -ForegroundColor Green
    $chatData = $chatResponse.Content | ConvertFrom-Json
    Write-Host "  Response: $($chatData.response.Substring(0, 100))..." -ForegroundColor Gray
} catch {
    Write-Host "✗ Chat failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Response Body: $($_.Exception.Response.Content)" -ForegroundColor Gray
}

# 5. Test with image
Write-Host ""
Write-Host "5. Testing image upload and vision..." -ForegroundColor Yellow
$imagePath = "E:\GitHup Projects\Multimodal-RAG-Core Project\img.jpeg"

if (Test-Path $imagePath) {
    try {
        # Create multipart form for image
        $boundary = [System.Guid]::NewGuid().ToString()
        $LF = "`r`n"
        $body = [System.Text.Encoding]::UTF8.GetBytes("--$boundary$LF")
        $body += [System.Text.Encoding]::UTF8.GetBytes("Content-Disposition: form-data; name=`"file`"; filename=`"img.jpeg`"$LF")
        $body += [System.Text.Encoding]::UTF8.GetBytes("Content-Type: image/jpeg$LF$LF")
        $body += [System.IO.File]::ReadAllBytes($imagePath)
        $body += [System.Text.Encoding]::UTF8.GetBytes("$LF--$boundary--$LF")
        
        $visionResponse = Invoke-WebRequest -Uri "$API_URL/upload" `
            -Method POST `
            -Headers $headers `
            -ContentType "multipart/form-data; boundary=`"$boundary`"" `
            -Body $body `
            -TimeoutSec 30
        
        Write-Host "✓ Image upload successful" -ForegroundColor Green
        $visionData = $visionResponse.Content | ConvertFrom-Json
        Write-Host "  Image ID: $($visionData.file_id)" -ForegroundColor Gray
        
        # Ask question about image
        $visionChatBody = @{
            message = "What is the total in QAR shown in this invoice image?"
        } | ConvertTo-Json
        
        $visionChatResponse = Invoke-WebRequest -Uri "$API_URL/chat" `
            -Method POST `
            -Headers $headers `
            -ContentType "application/json" `
            -Body $visionChatBody `
            -TimeoutSec 30
        
        Write-Host "✓ Vision chat successful" -ForegroundColor Green
        $visionChatData = $visionChatResponse.Content | ConvertFrom-Json
        Write-Host "  Vision Response: $($visionChatData.response)" -ForegroundColor Green
        
    } catch {
        Write-Host "✗ Image test failed: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "✗ Image file not found at $imagePath" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Test Complete ===" -ForegroundColor Cyan
