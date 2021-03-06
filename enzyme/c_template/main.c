#include<math.h>
#include<stdio.h>
#include<inttypes.h>
#include<string.h>
#include<stdlib.h>

#include "workspace.h"
${INCLUDE}

const uint64_t NI = ${NI};
const uint64_t NJ = ${NJ};
const uint64_t NK = ${NK};
const uint64_t MAX_VARS = ${MAX_VARS};
const uint64_t NUM_INPUTS = ${NUM_INPUTS};
const uint64_t NUM_OUTPUTS = ${NUM_OUTPUTS};

void workspace_init(Workspace * p)
{
    int64_t n_grid = (NI+2)*(NJ+2)*(NK+2);
    p->workspace = (double *)malloc(sizeof(double)*n_grid*MAX_VARS*2);
    p->source_workspace = p->workspace;
    p->sink_workspace = p->workspace + n_grid*MAX_VARS;
    int r = fread(p->workspace, sizeof(double), NI*NJ*NK*NUM_INPUTS, stdin);

    FOR_IJK {
        double * src = p->workspace + NUM_INPUTS * (k + j*NK + i*NK*NJ);
        double * dest = p->sink_workspace + OFFSET(i,j,k,NUM_INPUTS);
        memcpy(dest, src, NUM_INPUTS * sizeof(double));
    }
}

void workspace_swap_sync(Workspace * p, uint64_t n)
{
    double * sink = p->source_workspace;
    double * src = p->sink_workspace;
    p->source_workspace = src;
    p->sink_workspace = sink;

    FOR_IJ {
        memcpy(src+OFFSET(i,j,-1,n), src+OFFSET(i,j,NK-1,n), n*sizeof(double));
        memcpy(src+OFFSET(i,j,NK,n), src+OFFSET(i,j,0,n), n*sizeof(double));
    }
    FOR_IK {
        memcpy(src+OFFSET(i,-1,k,n), src+OFFSET(i,NJ-1,k,n), n*sizeof(double));
        memcpy(src+OFFSET(i,NJ,k,n), src+OFFSET(i,0,k,n), n*sizeof(double));
    }
    FOR_JK {
        memcpy(src+OFFSET(-1,j,k,n), src+OFFSET(NI-1,j,k,n), n*sizeof(double));
        memcpy(src+OFFSET(NI,j,k,n), src+OFFSET(0,j,k,n), n*sizeof(double));
    }
}

void workspace_finalize(Workspace * p)
{
    FOR_IJK {
        double * src = p->sink_workspace + OFFSET(i,j,k,NUM_OUTPUTS);
        double * dest = p->source_workspace + NUM_OUTPUTS * (k+j*NK+i*NK*NJ);
        memcpy(dest, src, NUM_OUTPUTS * sizeof(double));
    }
    int r = fwrite(p->source_workspace, sizeof(double),
                   NI*NJ*NK*NUM_OUTPUTS, stdout);
}

int main()
{
    Workspace buf;
    workspace_init(&buf);
    ${STAGES}
    workspace_finalize(&buf);
}
