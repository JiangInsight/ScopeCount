
struct ValidityColumn {
    vector<U> covered, missing;
    U rows_seen=0, end=0;
    void write(size_t w,U occupied,U absent) {
        if(!occupied)return;
        if(w>=covered.size())covered.resize(w+1);
        if(covered[w]&occupied)throw invalid_argument("duplicate rid in scope_validity");
        covered[w]|=occupied;
        if(absent){if(w>=missing.size())missing.resize(w+1);missing[w]|=absent;}
    }
    void block(U rid,U occupied,U absent) {
        size_t w=rid/64;unsigned shift=unsigned(rid%64);
        write(w,occupied<<shift,absent<<shift);
        if(shift)write(w+1,occupied>>(64-shift),absent>>(64-shift));
    }
};
idx_t validity_size(duckdb_function_info){return sizeof(ValidityColumn);}
void validity_init(duckdb_function_info,duckdb_aggregate_state state){new(state) ValidityColumn();}
void validity_free(duckdb_aggregate_state *states,idx_t n){
    for(idx_t i=0;i<n;i++)reinterpret_cast<ValidityColumn*>(states[i])->~ValidityColumn();
}
void validity_update(duckdb_function_info info,duckdb_data_chunk input,duckdb_aggregate_state *states){
    try {
        const idx_t n=duckdb_data_chunk_get_size(input);if(!n)return;
        auto idvec=duckdb_data_chunk_get_vector(input,0), col=duckdb_data_chunk_get_vector(input,1);
        auto* rid=static_cast<I*>(duckdb_vector_get_data(idvec));
        auto* valid_id=duckdb_vector_get_validity(idvec);auto* present=duckdb_vector_get_validity(col);
        bool linear=true;for(idx_t j=0;j<n;j++){
            if(valid_id&&!duckdb_validity_row_is_valid(valid_id,j))throw invalid_argument("null row id in scope_validity");
            if(rid[j]==UINT32_MAX)throw length_error("row identifier exceeds supported range");
            linear&=(states[j]==states[0] && U(rid[j])==U(rid[0])+j);
        }
        if(linear){
            auto& s=*reinterpret_cast<ValidityColumn*>(states[0]);s.rows_seen+=n;s.end=max(s.end,U(rid[n-1])+1);

            for(idx_t j=0;j<n;j+=64){
                const idx_t len=min<idx_t>(64,n-j);const U mask=len==64?~U(0):(U(1)<<len)-1;
                U absent=present?(~present[j/64]&mask):0;
                s.block(rid[j],mask,absent);
            }
        }else for(idx_t j=0;j<n;j++){
            auto& s=*reinterpret_cast<ValidityColumn*>(states[j]);s.rows_seen++;s.end=max(s.end,U(rid[j])+1);
            const bool missing=present&&!duckdb_validity_row_is_valid(present,j);s.block(rid[j],1,missing?1:0);
        }
    }catch(const exception&e){duckdb_aggregate_function_set_error(info,e.what());}
}
void validity_combine(duckdb_function_info info,duckdb_aggregate_state *src,duckdb_aggregate_state *dst,idx_t n){
    try{for(idx_t i=0;i<n;i++){
        auto &from=*reinterpret_cast<ValidityColumn*>(src[i]),&to=*reinterpret_cast<ValidityColumn*>(dst[i]);
        to.rows_seen+=from.rows_seen;to.end=max(to.end,from.end);
        for(size_t j=0;j<from.covered.size();j++)to.write(j,from.covered[j],j<from.missing.size()?from.missing[j]:0);
    }}catch(const exception&e){duckdb_aggregate_function_set_error(info,e.what());}
}
void validity_finalize(duckdb_function_info info,duckdb_aggregate_state *states,duckdb_vector result,idx_t n,idx_t offset){
    try{for(idx_t i=0;i<n;i++){
        auto& s=*reinterpret_cast<ValidityColumn*>(states[i]);
        if(s.rows_seen!=s.end)throw invalid_argument("scope_validity requires dense row ids from zero");
        vector<U> encoded{ s.end };encoded.insert(encoded.end(),s.missing.begin(),s.missing.end());
        duckdb_vector_assign_string_element_len(result,offset+i,reinterpret_cast<const char*>(encoded.data()),encoded.size()*sizeof(U));
    }}catch(const exception&e){duckdb_aggregate_function_set_error(info,e.what());}
}
void register_validity(duckdb_connection con){
    auto fn=duckdb_create_aggregate_function();
    auto rid=duckdb_create_logical_type(DUCKDB_TYPE_UINTEGER), col=duckdb_create_logical_type(DUCKDB_TYPE_BOOLEAN),bl=duckdb_create_logical_type(DUCKDB_TYPE_BLOB);
    duckdb_aggregate_function_set_name(fn,"scope_validity");
    duckdb_aggregate_function_add_parameter(fn,rid);duckdb_aggregate_function_add_parameter(fn,col);
    duckdb_aggregate_function_set_return_type(fn,bl);duckdb_aggregate_function_set_special_handling(fn);
    duckdb_aggregate_function_set_functions(fn,validity_size,validity_init,validity_update,validity_combine,validity_finalize);
    duckdb_aggregate_function_set_destructor(fn,validity_free);
    auto ok=duckdb_register_aggregate_function(con,fn);
    duckdb_destroy_aggregate_function(&fn);for(auto *v:{&rid,&col,&bl})duckdb_destroy_logical_type(v);
    if(ok!=DuckDBSuccess)throw runtime_error("could not register scope_validity");
}
void attach(duckdb_function_info info,duckdb_data_chunk args,duckdb_vector out){
    try{
        auto&reg=registry(info);lock_guard guard(reg.lock);
        for(idx_t j=0;j<duckdb_data_chunk_get_size(args);j++){
            auto started=Clock::now();
            auto nm=scalar<duckdb_string_t>(args,0,j);
            string backend(duckdb_string_t_data(&nm),duckdb_string_t_length(nm));
            auto n=scalar<I>(args,1,j);if(n==UINT32_MAX)throw length_error("row count exceeds supported range");
            auto fields=unpack(duckdb_data_chunk_get_vector(args,2),j);auto blobs=duckdb_data_chunk_get_vector(args,3);
            valid(blobs,j);auto slot=static_cast<duckdb_list_entry*>(duckdb_vector_get_data(blobs))[j];auto child=duckdb_list_vector_get_child(blobs);
            if(slot.length!=fields.size() || fields.size()>64)throw invalid_argument("field directory does not match bitmap columns");
            vector<vector<U>> masks(64);U seen=0;const size_t nw=(U(n)+63)/64;
            for(size_t k=0;k<fields.size();k++){
                auto field=fields[k];if(field>=64 || ((seen>>field)&1))throw invalid_argument("invalid or repeated bitmap field");
                seen|=U(1)<<field;valid(child,slot.offset+k);
                auto v=static_cast<duckdb_string_t*>(duckdb_vector_get_data(child))[slot.offset+k];
                auto bytes=duckdb_string_t_length(v);auto ptr=duckdb_string_t_data(&v);U header;
                if(bytes<8 || bytes%8 || bytes/8-1>nw)throw invalid_argument("invalid bitmap payload");
                memcpy(&header,ptr,8);if(header!=n)throw invalid_argument("row counts differ across bitmap columns");
                if(bytes>8){auto&w=masks[field];w.assign(nw,0);memcpy(w.data(),ptr+8,bytes-8);
                    if(n%64 && (w.back()>>(n%64)))throw invalid_argument("bitmap tail outside snapshot");}
            }
            unique_ptr<Snapshot> state;
#ifdef SCOPECOUNT_ROARING
            if(backend=="roaring"){
                state=make_unique<Snapshot>(backend,n);
                state->compressed=make_unique<compressed::Index>(n,fields,masks);
                state->stats.base_bytes=state->compressed->base_bytes;
                state->native_build_ns=elapsed(started);
                auto id=reg.next++;reg.state.emplace(id,move(state));
                static_cast<U*>(duckdb_vector_get_data(out))[j]=id;
                continue;
            }
#endif
            const bool usecols=backend=="bitmap"||backend=="words"||backend=="online";
            vector<U> signatures;
            if(!usecols||backend=="online"){

                U common=0;
                for(U field:fields){size_t set_count=0;for(U w:masks[field])set_count+=popcount(w);if(set_count>n/2)common|=U(1)<<field;}
                signatures.assign(n,common);
                for(U field:fields)for(size_t w=0;w<masks[field].size();w++){
                    U differences=masks[field][w]^((common>>field)&1?~U(0):U(0));
                    if(w+1==nw&&n%64)differences&=(U(1)<<(n%64))-1;
                    for(U v=differences;v;v&=v-1)signatures[64*w+countr_zero(v)]^=U(1)<<field;
                }
            }
            if(usecols){
                state=make_unique<Snapshot>(backend,n);
                if(backend=="online" && n){
                    state->tree=make_unique<Tree>(signatures);state->stats.base_bytes+=state->tree->t.capacity()*sizeof(Node);
                    for(auto& node:state->tree->t)state->stats.base_bytes+=4*node.p.capacity()+8*node.w.capacity()+4*node.pref.capacity();}
                state->columns=make_unique<Columns>(vector<U>{});
                auto&c=*state->columns;c.n=n;c.nw=nw;c.w=move(masks);
                for(unsigned k=0;k<64;k++)if(!c.w[k].empty()){
                    c.pref[k].resize(nw+1);
                    for(size_t w=0;w<nw;w++)c.pref[k][w+1]=c.pref[k][w]+popcount(c.w[k][w]);
                    state->stats.base_bytes+=c.w[k].capacity()*8+c.pref[k].capacity()*4;
                }
            }else state=make_unique<Snapshot>(backend,move(signatures));
            state->native_build_ns=elapsed(started);auto id=reg.next++;reg.state.emplace(id,move(state));
            static_cast<U*>(duckdb_vector_get_data(out))[j]=id;
        }
    }catch(const exception&e){duckdb_scalar_function_set_error(info,e.what());}
}
