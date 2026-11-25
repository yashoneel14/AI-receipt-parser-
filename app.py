import streamlit as st
from supabase import create_client
import cv2
import pytesseract
import pandas as pd
import re
from PIL import Image
import numpy as np

# Page Config
st.set_page_config(page_title="AI Receipt Line-Item Parser", layout="wide")

# CSS fonting
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Montserrat', sans-serif !important;
    }
    </style>
""", unsafe_allow_html=True)

st.title("Receipt Item Parser🧾")
st.write("Upload a receipt to automatically split and categorize individual purchases.")

# Initialising session state to store individual transactions
if 'expenses' not in st.session_state:
    st.session_state.expenses = pd.DataFrame(columns=["Item Name", "Category", "Price"])

#SUPABASE CONNECTION 
@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )

def add_expense(item: str, cost: float, expense_type: str):
    get_supabase().table("expenses").insert({
        "item": item,
        "cost": cost,
        "expense_type": expense_type,
    }).execute()

def get_expenses():
    res = (
        get_supabase()
        .table("expenses")
        .select("item, cost, expense_type, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data

#for deletion
def delete_expense(expense_id: int):
    get_supabase().table("expenses").delete().eq("id", expense_id).execute()
# Image Preprocessing 
def preprocess_image(image):
    open_cv_image = np.array(image.convert('RGB'))
    open_cv_image = open_cv_image[:, :, ::-1].copy()
    gray = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (0, 0), fx=2, fy=2)
    _, thresh = cv2.threshold(resized, 140, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return thresh

# Line Item Parser
def parse_line_items(text):
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Try to extract merchant name from first non-empty line
    itemized_list = []
    
    #  words to ignore
    skip_keywords = ["expires", "total", "visa", "charge", "rec#", "vcd#", "thank", "come", "discount", "cash", "balance", "debit", "card", "%"]
    
    for line in lines:
        line_lower = line.lower()
        if any(skip in line_lower for skip in skip_keywords):
            continue
            
        # Look for a price pattern 
        price_match = re.search(r'(-?\d+\.\d{2})', line)
        
        if price_match:
            price_str = price_match.group(1)
            price = float(price_str)
            
            # Clean up item name
            item_name = line.replace(price_str, "").strip()
            item_name = re.sub(r'\s+[NF]\s*$', '', item_name).strip()
            item_name = re.sub(r'^\d+\s+', '', item_name).strip()
            
            if len(item_name) < 2:
                continue
                
            # Keyword based categorization
            item_lower = item_name.lower()
            if any(k in item_lower for k in ["tv", "led", "bluetooth", "electronic", "phone", "gadget", "device", "mobile", "smart-phone", "headphones", "earphones", "airpods", "earpods", "watch", "smart"]):
                category = "Electronics"
            elif any(k in item_lower for k in ["shampoo", "conditioner", "health", "beauty", "soap", "cream", "pharmacy", "face", "medicine", "cream", "tablets"]):
                category = "Health & Self-Care"
            elif any(k in item_lower for k in ["food", "grocery", "milk", "eggs", "bread", "cafe", "tea", "coffee", "snack", "water", "lunch", "dinner", "breakfast", "brunch", "biscuits", "chocolates", "fruits", "vegetables"]):
                category = "Food & Groceries"
            elif any(k in item_lower for k in ["shirt", "pants", "shoes", "cloth", "wear", "jeans", "socks", "t-shirt", "trousers", "chain", "bracelet", "necklace", "sandals", "skirt", "frock", "crop", "top", "denim", "clip"]):
                category = "Shopping"
            elif any(k in item_lower for k in ["tax", "taxes", "GST", "CGST", "SGST"]):
                category = "tax"
            else:
                category = "General Expense"
                
            itemized_list.append({
                "Item Name": item_name,
                "Category": category,
                "Price": price
            })
            
    # If OCR returns nothing valid, the dashboard provides a blank row so the user can type themselves manually
    if not itemized_list:
        st.write("We are having issues identifying the purchase. Mind filling it up manually?")
        itemized_list.append({
            "Item Name": "",
            "Category": "General Expense",
            "Price": 0.0
        })
        
    return itemized_list

# File uploader UI
uploaded_file = st.file_uploader("Upload Receipt Image (PNG, JPG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Uploaded Receipt")
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Image", use_column_width=True)
        
    with col2:
        st.subheader("Extracted Line Items & Verification")
        with st.spinner("Parsing items using OCR..."):
            processed_img = preprocess_image(image)
            extracted_text = pytesseract.image_to_string(processed_img)
            
            parsed_items = parse_line_items(extracted_text)
            
            with st.form("confirm_form"):
                st.write("Review, edit, or add items below before submitting:")
                
                temp_df = pd.DataFrame(parsed_items)
                # num_rows="dynamic" lets you click '+' to add rows manually if OCR misses something
                edited_df = st.data_editor(temp_df, use_container_width=True, num_rows="dynamic", hide_index=True)
                
                submit_button = st.form_submit_button("Add Items to Dashboard")
                
                if submit_button:
                    st.session_state.expenses = pd.concat([st.session_state.expenses, edited_df], ignore_index=True)
                    st.success("Items successfully added and categorized!")
                    
                    # save items to database 
                    try:
                        for _, row in edited_df.iterrows():
                            item_val = str(row.get("Item Name", "")).strip()
                            cat_val = str(row.get("Category", "General Expense")).strip()
                            price_val = float(row.get("Price", 0.0))
                            if item_val:
                                add_expense(item_val, price_val, cat_val)
                        st.markdown('<p style="color:#ffffff;font-weight:600;">Saved items to database.</p>', unsafe_allow_html=True)
                    except Exception as e:
                        st.markdown(f'<p style="color:#ffffff;font-weight:600;">Database save error: {e}</p>', unsafe_allow_html=True)

    with st.expander("View Raw OCR Text"):
        st.text(extracted_text)

# Dashboard Section
st.markdown("---")
st.header("📊 Purchase Analytics")

if not st.session_state.expenses.empty:
    m1, m2 = st.columns(2)
    total_spent = st.session_state.expenses["Price"].sum()
    total_items = len(st.session_state.expenses)
    
    m1.metric("Total Tracked Spending", f"${total_spent:,.2f}")
    m2.metric("Total Items Logged", total_items)
    
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.subheader("Spending by Category")
        category_sum = st.session_state.expenses.groupby("Category")["Price"].sum()
        st.bar_chart(category_sum)
        
    with col_chart2:
        st.subheader("All Logged Line Items")
        st.dataframe(st.session_state.expenses, use_container_width=True)
else:
    st.info("No items processed yet. Upload a receipt above to populate your itemized dashboard!")
   
# making sure database is persistant     
st.markdown("---")
st.markdown('<h3 style="color:#107AB0;">Saved Expenses </h3>', unsafe_allow_html=True)
try:
    db_rows = get_expenses()
    if db_rows:
        db_df = pd.DataFrame(db_rows).drop(columns=["id"], errors="ignore")
        st.dataframe(db_df, use_container_width=True, hide_index=True)

        # Let user pick a row to delete
        options = {
            f"{row['item']} — ${row['cost']} ({row['expense_type']}) [ID {row['id']}]": row["id"]
            for row in db_rows
        }
        selected_label = st.selectbox("Select an item to delete:", list(options.keys()))

        if st.button("Delete Selected Expense"):
            delete_expense(options[selected_label])
            st.rerun()
    else:
        st.markdown('<p style="color:#107AB0;">No rows saved in database yet.</p>', unsafe_allow_html=True)
except Exception as e:
    st.markdown(f'<p style="color:#107AB0;">Could not load expenses from database: {e}</p>', unsafe_allow_html=True)