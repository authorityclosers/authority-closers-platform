# Sales Xray web image inputs

The frozen Sales Xray learner route imports the Sales workspace app and client.
The existing Docker web builder copied only the three prior app manifests and
source trees. It now copies the Sales app/client manifests before the locked
workspace install and the Sales app source before building the learner image.

Independent review confirmed the missing build inputs and the three COPY
corrections. Integrated conversation/composition tests passed321cases, and the
native signals build plus52signal tests passed separately. Those checks do not
establish the web image result. Exact-candidate CI must build and start the
images successfully before this follow-on can be promoted.
