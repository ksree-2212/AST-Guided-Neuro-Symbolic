       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
      ******************************************************************
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GREETING      PIC X(20) VALUE "HELLO FROM COBOL4J!".
       PROCEDURE DIVISION.
       MAIN-RTN.
           DISPLAY WS-GREETING.
           STOP RUN.
