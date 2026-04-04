import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression



def train_model(training_csv_path: str = "/data4/RADCOM/Mukesh/1_PAM_Parsing_Mukesh/Full_load_new.csv"):
      # -----------------------------
    # Load & train model
    # -----------------------------
    time_df = pd.read_csv(training_csv_path)

    X_train = time_df[["numberOfPackets"]].astype(float) / 1000.0
    y_train = time_df["Execution_Time_sec"].astype(float)

    model = LinearRegression()
    model.fit(X_train, y_train)

    # Training residual stats (for anomaly threshold)
    y_train_pred = model.predict(X_train)
    residuals = y_train - y_train_pred
    sigma = np.std(residuals)

    return model,sigma

def predict_latency(
    Final_dataset: pd.DataFrame,
    
    k: float = 3.0
) -> pd.DataFrame:
    """
    Train a Linear Regression model using sklearn and
    predict execution latency + detect anomalies.

    Adds:
    - Predicted_Execution_Time_sec
    - Is_Anomaly
    """
    model,sigma = train_model()


    # -----------------------------
    # Apply model to Final_dataset
    # -----------------------------
    df = Final_dataset.copy()

    X_test = df[["numberOfPackets"]].astype(float) / 1000.0

    df["Predicted_Execution_Time_sec"] = model.predict(X_test)

    df["Residual"] = (
        df["Execution_Time_sec"] - df["Predicted_Execution_Time_sec"]
    )

    df["Is_Anomaly"] = df["Residual"] > k * sigma
    


    df = df.drop(columns=["Residual"], errors="ignore")
    # Add Task column after 'numberOfPackets'


    df = df.reindex(columns=[
    'Flow_ID',
    'Trace_ID',
    'Start_Time',
    'End_Time',
    'user',
    'numberOfPackets',
    'Task',
    'Execution_Time_sec',
    'Predicted_Execution_Time_sec',
    'Is_Anomaly'
])


    return df
