       IDENTIFICATION DIVISION.
       PROGRAM-ID. BILLING.
      ******************************************************************
      * AST-Guided Neuro-Symbolic RAG Evaluation Sample
      * Corresponds to billing.py from the research paper
      ******************************************************************
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CART-TOTAL        PIC 9(5)V99 VALUE 10000.00.
       01  WS-DISCOUNT-PCT      PIC 99      VALUE 10.
       01  WS-DISCOUNT-AMT      PIC 9(5)V99 VALUE 00000.00.
       01  WS-DISCOUNTED-TOTAL  PIC 9(5)V99 VALUE 00000.00.
       01  WS-TAX-RATE          PIC V99     VALUE .08.
       01  WS-TAX-AMT           PIC 9(5)V99 VALUE 00000.00.
       01  WS-FINAL-TOTAL       PIC 9(5)V99 VALUE 00000.00.
       01  WS-DISPLAY-NUM       PIC ZZZ99.99.

       PROCEDURE DIVISION.
       MAIN-RTN.
           DISPLAY "=== BILLING SYSTEM START ===".
           PERFORM CHECKOUT-PARA.
           DISPLAY "FINAL INVOICE TOTAL: " WS-FINAL-TOTAL.
           DISPLAY "=== BILLING SYSTEM COMPLETE ===".
           STOP RUN.

       CHECKOUT-PARA.
      * Compute final total for shopping cart, applying discount then tax
           PERFORM APPLY-DISCOUNT-PARA.
           PERFORM CALCULATE-TAX-PARA.
           COMPUTE WS-FINAL-TOTAL = WS-DISCOUNTED-TOTAL + WS-TAX-AMT.
           MOVE WS-FINAL-TOTAL TO WS-DISPLAY-NUM.
           DISPLAY "CHECKOUT FINISHED: $" WS-DISPLAY-NUM.

       APPLY-DISCOUNT-PARA.
      * Apply percentage discount to the cart total
           COMPUTE WS-DISCOUNT-AMT = WS-CART-TOTAL * WS-DISCOUNT-PCT / 100.
           COMPUTE WS-DISCOUNTED-TOTAL = WS-CART-TOTAL - WS-DISCOUNT-AMT.
           MOVE WS-DISCOUNTED-TOTAL TO WS-DISPLAY-NUM.
           DISPLAY "DISCOUNTED SUBTOTAL: $" WS-DISPLAY-NUM.

       CALCULATE-TAX-PARA.
      * Calculate tax owed on the discounted amount using WS-TAX-RATE
           COMPUTE WS-TAX-AMT = WS-DISCOUNTED-TOTAL * WS-TAX-RATE.
           MOVE WS-TAX-AMT TO WS-DISPLAY-NUM.
           DISPLAY "TAX CALCULATED: $" WS-DISPLAY-NUM.
