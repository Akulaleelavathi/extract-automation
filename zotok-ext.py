
import json
import os
import csv
from datetime import datetime
import requests
from azure.storage.blob import BlobServiceClient
import io

# Azure Storage Configuration
AZURE_STORAGE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=zonoaimodels;AccountKey=6Sb49L2N7hxTGdPhW/6hwwk8VrCeZ6xRQbNJnNbYA58bIICGSX8tU0wSDcpzMNSVAsIegohBJWbu+AStRdU0Qw==;EndpointSuffix=core.windows.net"
BLOB_CONTAINER_INPUT = "image-text-input"
BLOB_CONTAINER_OUTPUT = "image-text-output"

# Folder Configuration
INPUT_FOLDER = "input"
OUTPUT_FOLDER = "output"
LOG_FILE = "results.csv"
ACCURACY_FILE = "accuracy_report.csv"

# Expected Results (for accuracy checks)
EXPECTED_RESULTS_FILE = "expected_results.json"

# Ensure folders exist
os.makedirs(INPUT_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Initialize Azure Blob Service
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

def download_images_from_azure():
    responses = []
    try:
        container_client = blob_service_client.get_container_client(BLOB_CONTAINER_INPUT)
        for blob in container_client.list_blobs():
            blob_client = container_client.get_blob_client(blob.name)
            local_file_path = os.path.join(INPUT_FOLDER, os.path.basename(blob.name))
            with open(local_file_path, "wb") as file:
                file.write(blob_client.download_blob().readall())
            responses.append({"Image Name": blob.name, "Download Status": "Success"})
    except Exception as e:
        responses.append({"Error": f"Error downloading images: {str(e)}"})
    return responses

def convert_image_to_text(image_path):
    url = "https://api-qa.zono.digital/bot/api/v1/parse-file/v2?sellerWorkspaceId=7c4e9b03-cd70-4fc6-9a27-edd56dd3d813"
    try:
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
            files = {'file': ('image.jpeg', io.BytesIO(image_data), 'image/jpeg')}
            response = requests.post(url, files=files, headers={
                # "authorization": "Bearer <YOUR_BEARER_TOKEN>",
                "User-Agent": "Mozilla/5.0",
            })
            response.raise_for_status()
            return response.json()
    except Exception as e:
        raise RuntimeError(f"Error converting image to text: {str(e)}")

def extract_fields_from_text(parsed_text):
    url = "https://zotok-qa-pf.azurewebsites.net/score"
    headers = {"Accept": "application/json, text/plain, */*", "Content-Type": "application/json"}
    payload = {"body": {"input": parsed_text, "workspaceId": "4c88973d-cbe3-4e94-9bb5-4b61c322b86d"}, "route": "product_parsing"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise RuntimeError(f"Error extracting fields: {str(e)}")

def map_products(parsed_text):
    workspaceid = "d9301ddf-2c64-4680-8d3f-f460e07ed219"
    url = f"https://api-qa.zono.digital/hub/commerce-v2/cognitive/search/{workspaceid}?sellerWorkspaceId={workspaceid}"
    headers = {
        "accept": "application/json",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjp7ImlkIjoiNGI5MjE0MzItYjAyNy00ZGMyLWE5YjctNDkzZDIzMmUyZjYzIiwid29ya3NwYWNlSWQiOiI2ZjNjODFmMS0xM2EzLTRlMGYtYmZkZS1hMmI3MWYyNjM2YmYiLCJ3b3Jrc3BhY2VSb2xlcyI6WyJhZG0iXX0sImlhdCI6MTczNjc3MjAwMSwiZXhwIjoxNzM5MTkxMjAxfQ.wzDe5MzJ3t_mUHoFpnmAx01lIUZhPbqX7bUQVfxsnvU",
        "content-type": "application/json",
    }
    payload = {"products": [parsed_text]}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Error mapping products: {e}")

def upload_csv_to_azure(file_path, container_name, blob_name):
    try:
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        with open(file_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
        print(f"CSV file uploaded successfully to Azure as {blob_name}.")
    except Exception as e:
        print(f"Error uploading CSV to Azure: {str(e)}")
        
def check_accuracy(map_products, expected_products):
    """
    Compare parsed product names with expected product names and calculate accuracy.
    
    :param parsed_products: List of product names from the mapped response.
    :param expected_products: List of product names from the expected results JSON.
    :return: Accuracy percentage, matches, mismatches.
    """
    # Normalize the products for comparison (case-insensitive and strip whitespace)
    normalized_parsed = [product.strip().lower() for product in map_products]
    normalized_expected = [product.strip().lower() for product in expected_products]

    # Count matches (products in expected that are found in parsed)
    matches = sum(1 for product in normalized_expected if product in normalized_parsed)
    
    # Count mismatches (products in expected that are not in parsed)
    mismatches = len(normalized_expected) - matches

    # Calculate accuracy percentage
    accuracy = (matches / len(normalized_expected)) * 100 if normalized_expected else 0
    
    return accuracy, matches, mismatches

def process_images():
    # Load expected results
    with open(EXPECTED_RESULTS_FILE, "r") as file:
        expected_results = json.load(file)

    csv_file_path = os.path.join(OUTPUT_FOLDER, LOG_FILE)
    accuracy_file_path = os.path.join(OUTPUT_FOLDER, ACCURACY_FILE)

    with open(csv_file_path, "w", newline="") as csvfile, open(accuracy_file_path, "w", newline="") as acc_file:
        fieldnames = ["Image Name", "Step", "Response"]
        acc_fieldnames = ["Image Name", "Accuracy"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        acc_writer = csv.DictWriter(acc_file, fieldnames=acc_fieldnames)

        writer.writeheader()
        acc_writer.writeheader()

        for image_name in os.listdir(INPUT_FOLDER):
            if not image_name.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            image_path = os.path.join(INPUT_FOLDER, image_name)

            try:
                # Step 1: Convert Image to Text
                parsed_response = convert_image_to_text(image_path)
                writer.writerow({"Image Name": image_name, "Step": "Convert Image to Text", "Response": json.dumps(parsed_response)})
                parsed_text = parsed_response.get("parsedText", "")

                # Step 2: Extract Fields
                extracted_fields = extract_fields_from_text(parsed_text)
                writer.writerow({"Image Name": image_name, "Step": "Extract Fields", "Response": json.dumps(extracted_fields)})

                # Step 3: Map Products
                if parsed_text:
                    mapped_products = map_products(parsed_text)
                    writer.writerow({"Image Name": image_name, "Step": "Map Products", "Response": json.dumps(mapped_products)})

                    # Log Mapped Products and Expected Products
                    parsed_product_names = [product['productName'] for product in mapped_products['payload']['distributorUploadedProduct'][0]['mappedProducts']]
                    expected_product_names = expected_results['Items']  # Get products from the 'Items' key
                    print(f"Parsed Products: {parsed_product_names}")
                    print(f"Expected Products: {expected_product_names}")

                    # Step 4: Check Accuracy
                    accuracy, matches, mismatches = check_accuracy(parsed_product_names, expected_product_names)

                    # Writing the accuracy result to a CSV file
                    acc_writer.writerow({"Image Name": image_name, "Accuracy": f"{accuracy:.2f}%"})

                    print(f"Accuracy for {image_name}: {accuracy:.2f}%")
                    print(f"Matches: {matches}, Mismatches: {mismatches}")

                    # Print matched and mismatched products for clarity
                    matched = [product for product in parsed_product_names if product in expected_product_names]
                    mismatched = [product for product in parsed_product_names if product not in expected_product_names]
                    
                    # print(f"Matched Products: {matched}")
                    # print(f"Mismatched Products: {mismatched}")

            except Exception as e:
                writer.writerow({"Image Name": image_name, "Step": "Error", "Response": str(e)})


            except Exception as e:
                writer.writerow({"Image Name": image_name, "Step": "Error", "Response": str(e)})

    upload_csv_to_azure(csv_file_path, BLOB_CONTAINER_OUTPUT, LOG_FILE)
    upload_csv_to_azure(accuracy_file_path, BLOB_CONTAINER_OUTPUT, ACCURACY_FILE)



if __name__ == "__main__":
    download_responses = download_images_from_azure()
    with open(os.path.join(OUTPUT_FOLDER, "download_responses.json"), "w") as file:
        json.dump(download_responses, file)

    process_images()































