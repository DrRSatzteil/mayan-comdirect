# mayan-comdirect
Addon for Mayan EDMS. Augments your invoices with acutal payment data from your Comdirect bank account. 

Credits go to m42e and the great mayan-automatic-metadata addon which I used as architectural blueprint and for Mayan API handling.

!!!Important!!! Please use at your own risk. Incorrect usage may lead to an account lock. Note that only P_TAN_PUSH TAN method is supported (set this as preferred TAN method in your account) since this is the only method that won't require additional user interaction.

Note that this project is not yet finished and there is no complete use case implemented yet. Comdirect API handling is pretty complete though and mayan API handling was taken over from m42e/mayan-automatic-metadata.

First use case will be detection if invoice has been paid already.

Unfortunately Comdirect does not support the triggering of transactions. As soon as this is possible I will implement this feature.

