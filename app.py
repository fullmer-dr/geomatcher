import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

st.title("Company-Feature Matcher")

# Upload GeoJSON file
geojson_file = st.file_uploader("Upload a GeoJSON file", type="geojson")

# Upload CSV file
csv_file = st.file_uploader("Upload a CSV file", type="csv")

def get_features(geojson_file):
    # Read lines until a non-empty line is found
    first_line = ''
    while not first_line.strip():
        first_line = geojson_file.readline().decode('utf-8')
    
    geojson_file.seek(0)  # Reset file pointer to the beginning
    
    # Load neighborhood data
    neighborhoods = gpd.read_file(geojson_file)
    
    # Attempt to extract 'name' from properties
    if 'name' not in neighborhoods.columns:
        if 'properties' in neighborhoods.columns:
            neighborhoods['name'] = neighborhoods['properties'].apply(lambda x: x.get('hood', None))
    
    # Check if 'name' column exists in features
    name_exists = 'name' in neighborhoods.columns and neighborhoods['name'].notnull().any()
    if not name_exists:
        # Try to find a suitable fallback column
        possible_fallbacks = ['OBJECTID', 'id', 'neighborhood', 'area']
        fallback_column = next((col for col in possible_fallbacks if col in neighborhoods.columns), None)
        
        if fallback_column:
            st.warning(f"'name' column not found in GeoJSON. Using '{fallback_column}' as a fallback.")
            neighborhoods['name'] = neighborhoods[fallback_column].astype(str)
        else:
            st.info("No suitable identifier column found in GeoJSON for counting. Filtering will still work.")
            neighborhoods['name'] = neighborhoods.index.astype(str)  # Use index as a fallback for filtering
    
    return neighborhoods[['name', 'geometry']], name_exists

def filter_companies_in_features(geojson_file, csv_file):
    neighborhoods, name_exists = get_features(geojson_file)
    if neighborhoods is None:
        return None, 0, 0, None
    
    # Read lines until a non-empty data row is found to determine the delimiter
    first_line = ''
    while not first_line.strip() or all(field.strip() == '' for field in first_line.split(',')):
        first_line = csv_file.readline().decode('utf-8')
    
    csv_file.seek(0)  # Reset file pointer to the beginning
    delimiter = ';' if ';' in first_line else ','
    
    # Load company data with the determined delimiter, skipping initial empty lines
    companies_df = pd.read_csv(csv_file, sep=delimiter, skip_blank_lines=True)
    
    # Drop completely empty rows
    companies_df.dropna(how='all', inplace=True)
    
    # Ensure the required columns are present
    if 'LATITUDE' not in companies_df.columns or 'LONGITUDE' not in companies_df.columns:
        st.error("CSV file must contain 'LATITUDE' and 'LONGITUDE' columns.")
        return None, 0, 0, None
    
    # Identify the funding column
    funding_column = next((col for col in companies_df.columns if col.startswith('TOTAL FUNDING')), None)
    
    # Create geometry points from latitude and longitude
    company_points = [Point(xy) for xy in zip(companies_df['LONGITUDE'], companies_df['LATITUDE'])]
    companies = gpd.GeoDataFrame(companies_df, geometry=company_points, crs=neighborhoods.crs)
    
    # Spatial join to filter companies within features
    companies_in_features = gpd.sjoin(companies, neighborhoods, how='inner', predicate='intersects')
    
    if name_exists:
        # Return companies with feature name information
        return companies_in_features.drop(columns=['geometry', 'index_right']), len(companies_df), len(companies_in_features), funding_column
    else:
        # Return companies generally contained in the GeoJSON area
        filtered_companies = companies_in_features.drop(columns=['geometry', 'index_right']).drop_duplicates()
        return filtered_companies, len(companies_df), len(filtered_companies), funding_column

def calculate_funding(geojson_file, csv_file):
    filtered_companies, input_count, output_count, funding_column = filter_companies_in_features(geojson_file, csv_file)
    if filtered_companies is None:
        return None
    
    # Calculate total funding and company count per feature
    if funding_column:
        total_funding_entire_area = filtered_companies[funding_column].sum()
        funding_per_feature = filtered_companies.groupby('name').agg(
            company_count=('name', 'size'),
            funding_amount=(funding_column, 'sum')
        ).reset_index()
        funding_per_feature.columns = ['Feature', 'Company Count', 'Funding Amount']
        
        # Add the entire area total as the first row
        entire_area_row = pd.DataFrame([['Entire Area', output_count, total_funding_entire_area]], columns=['Feature', 'Company Count', 'Funding Amount'])
        result = pd.concat([entire_area_row, funding_per_feature], ignore_index=True)
    else:
        # Only calculate company count per feature
        company_count_per_feature = filtered_companies['name'].value_counts().reset_index()
        company_count_per_feature.columns = ['Feature', 'Company Count']
        
        # Add the entire area total as the first row
        entire_area_row = pd.DataFrame([['Entire Area', output_count]], columns=['Feature', 'Company Count'])
        result = pd.concat([entire_area_row, company_count_per_feature], ignore_index=True)
    
    return result

if geojson_file and csv_file:
    neighborhoods, name_exists = get_features(geojson_file)
    
    # Always show the filter button
    if neighborhoods is not None and st.button("Filter Companies within GeoJSON Area"):
        filtered_companies, input_count, output_count, _ = filter_companies_in_features(geojson_file, csv_file)
        if filtered_companies is not None:
            if name_exists:
                st.write("Filtered Companies by Feature Name")
            else:
                st.write("Filtered Companies within GeoJSON Area")
            st.dataframe(filtered_companies)
            st.write(f"Input Rows: {input_count}, Output Rows: {output_count}")
    
    # Conditionally show the count and funding button
    if neighborhoods is not None and name_exists:
        if st.button("Count and Calculate Funding per Feature"):
            funding_result = calculate_funding(geojson_file, csv_file)
            if funding_result is not None:
                st.write("Funding Amounts")
                st.dataframe(funding_result)
    elif neighborhoods is not None:
        st.markdown("**Count and Calculate Funding per Feature** button is disabled because no suitable identifier column is found in the GeoJSON file.")

# Add a concise description at the bottom of the app
st.markdown("""
### About This Tool

This application helps you match companies to geographical features using GeoJSON and CSV files. 

- **GeoJSON File**: Defines geographical areas (e.g., cities, neighborhoods etc.).
- **CSV File**: A Dealroom export in csv format that contains latitude and longitude.
- **Functionality**:
  - **Filter Companies**: Identify companies located within specified geographical areas (features). This requires at least: a geojson, a dealroom export as csv that contains company name, latitude, and longitude.
  - **Count Companies and Calculate Funding**: Count the number of companies per area (feature) and calculate their total funding. This requires at least: a geojson (with features for subareas that have a property name), a dealroom export as csv that contains company name, latitude, longitude, and total funding amount. 

For more GeoJSON files, visit [this resource](https://github.com/codeforgermany/click_that_hood/tree/main/public/data).
""")
