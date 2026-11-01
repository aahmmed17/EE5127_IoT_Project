

File	  Rows	   Period	                           Occupied
test1	2,665	2 Feb 14:19 to 4 Feb 10:43	        36.5%
train	8,143	4 Feb 17:51 to 10 Feb 09:33         21.2%
test2	9,752	11 Feb 14:48 to 18 Feb 09:19	  21.0%



Test Block: test2, start row: 1020: 2015-02-12 07:47:59 -> 2015-02-12 09:16:59
interval min/max: 59/61 s
label changes: [('08:31:00', 1), ('08:32:59', 0), ('08:37:00', 1)]

Scaling: temperature and humidity ×100 stored as int16, light and CO₂ unscaled

Set A = the 90-row held-out block, Set B = all of test1 (2,665 rows), with the reason for each
Humidity ratio deliberately left off the node and computed at the gateway

Training policy: train only on the train file, validate on test1, leave the rest of test2 untouched until D3

Device Name: OccNode
UUID: 12345678-1234-5678-1234-56789abcdef1


