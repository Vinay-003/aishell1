# This will generate ModuleNotFoundError since 'pandas' is likely not installed
import pandas as pd

def analyze_data():
    # Create a simple DataFrame
    df = pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie'],
        'age': [25, 30, 35]
    })
    print(df)

if __name__ == "__main__":
    analyze_data()
